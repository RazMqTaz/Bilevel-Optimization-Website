import os
import sys
import re
import json
import logging
import tempfile
import sqlite3

from celery import Celery
from redis import Redis

sys.path.insert(0, os.path.abspath("SACEProject"))
from SACEProject.main import main

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Celery app with Redis as both broker and result backend
celery_app = Celery(
    "sace_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Prefetch 1 task at a time since SACE jobs are long-running
    worker_prefetch_multiplier=1,
    # Acknowledge tasks only after completion (prevents losing jobs on crash)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


def get_db():
    conn = sqlite3.connect("submissions.db")
    conn.row_factory = sqlite3.Row
    return conn


class RedisOutputCapture:
    """Captures stdout/stderr and streams to Redis in real-time."""

    def __init__(self, job_id: int, redis: Redis, original_stream):
        self.job_id = job_id
        self.redis = redis
        self.key = f"job_output:{job_id}"
        self._original = original_stream

    def write(self, s: str):
        if not s:
            return 0
        # Append to Redis key
        self.redis.append(self.key, s)
        # Publish for any live listeners (WebSocket/SSE)
        self.redis.publish(f"job_stream:{self.job_id}", s)
        # Also write to terminal for debugging
        self._original.write(s)
        self._original.flush()
        return len(s)

    def flush(self):
        self._original.flush()

    def fileno(self):
        return self._original.fileno()


class RedisLoggingHandler(logging.Handler):
    """Sends Python logging output to Redis."""

    def __init__(self, job_id: int, redis: Redis):
        super().__init__()
        self.job_id = job_id
        self.redis = redis
        self.key = f"job_output:{job_id}"

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            self.redis.append(self.key, msg)
            self.redis.publish(f"job_stream:{self.job_id}", msg)
        except Exception:
            self.handleError(record)


@celery_app.task(bind=True, name="run_sace_job")
def run_sace_job(self, batch_config: dict, job_id: int) -> dict:
    """Execute a SACE optimization job."""
    output_key = f"job_output:{job_id}"

    # Initialize empty output in Redis
    redis_client.set(output_key, "")
    # Set a TTL so old job outputs don't live forever (24 hours)
    redis_client.expire(output_key, 86400)

    # Mark as running
    conn = get_db()
    conn.execute("UPDATE submissions SET status='running' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

    # Redirect stdout AND stderr to Redis
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = RedisOutputCapture(job_id, redis_client, old_stdout)
    sys.stderr = RedisOutputCapture(job_id, redis_client, old_stderr)

    # Add a logging handler so library log messages also go to Redis
    log_handler = RedisLoggingHandler(job_id, redis_client)
    log_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)

    os.environ["PYTHONUNBUFFERED"] = "1"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(batch_config, tmp)
            tmp.flush()
            main(tmp.name)

        # Parse captured output to find the results CSV filepath
        output_str = redis_client.get(output_key) or ""
        filepath_matches = re.findall(
            r"All results have been saved to:\s*(.+)", output_str
        )

        result_content = ""
        if filepath_matches:
            raw_filepath = filepath_matches[-1].strip()
            actual_filepath = None

            # Search for the history CSV by timestamp
            timestamp_match = re.search(r"(\d{8}-\d{6})", raw_filepath)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                history_dirs = [
                    "results/history",
                    os.path.join("SACEProject", "results/history"),
                ]
                for history_dir in history_dirs:
                    if os.path.exists(history_dir):
                        for filename in os.listdir(history_dir):
                            if timestamp in filename and filename.endswith(".csv"):
                                actual_filepath = os.path.join(history_dir, filename)
                                break
                    if actual_filepath:
                        break

            # Fallback to the summary file path
            if not actual_filepath:
                candidate_paths = [
                    raw_filepath,
                    os.path.join("SACEProject", raw_filepath),
                ]
                for path in candidate_paths:
                    if os.path.exists(path):
                        actual_filepath = path
                        break

            if actual_filepath:
                with open(actual_filepath, "r") as f:
                    result_content = f.read()

        # Mark complete and save result data
        conn = get_db()
        conn.execute(
            "UPDATE submissions SET status='complete', result_data=? WHERE id=?",
            (result_content, job_id),
        )
        conn.commit()
        conn.close()

        # Notify listeners that the job finished
        redis_client.publish(
            f"job_stream:{job_id}", "\n[DONE]\n"
        )
        redis_client.set(f"job_status:{job_id}", "complete")

        return {"job_id": job_id, "status": "complete"}

    except Exception as e:
        error_msg = f"\n[ERROR] Job {job_id} failed: {e}\n"
        redis_client.append(output_key, error_msg)
        redis_client.publish(f"job_stream:{job_id}", error_msg)
        redis_client.set(f"job_status:{job_id}", "failed")

        conn = get_db()
        conn.execute(
            "UPDATE submissions SET status='failed' WHERE id=?", (job_id,)
        )
        conn.commit()
        conn.close()

        return {"job_id": job_id, "status": "failed", "error": str(e)}

    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        root_logger.removeHandler(log_handler)
        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except OSError:
            pass