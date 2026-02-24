import os
import sys
import json
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
    """Captures stdout and streams it to Redis in real-time."""

    def __init__(self, job_id: int, redis: Redis):
        self.job_id = job_id
        self.redis = redis
        self.key = f"job_output:{job_id}"
        self._old_stdout = sys.stdout

    def write(self, s: str):
        if not s:
            return 0
        # Append to Redis key
        self.redis.append(self.key, s)
        # Publish for any live listeners (WebSocket/SSE)
        self.redis.publish(f"job_stream:{self.job_id}", s)
        # Also write to worker terminal for debugging
        self._old_stdout.write(s)
        self._old_stdout.flush()
        return len(s)

    def flush(self):
        self._old_stdout.flush()

    def fileno(self):
        return self._old_stdout.fileno()


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

    # Redirect stdout to Redis
    capture = RedisOutputCapture(job_id, redis_client)
    old_stdout = sys.stdout
    sys.stdout = capture

    os.environ["PYTHONUNBUFFERED"] = "1"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(batch_config, tmp)
            tmp.flush()
            main(tmp.name)

        # Mark complete
        conn = get_db()
        conn.execute(
            "UPDATE submissions SET status='complete' WHERE id=?", (job_id,)
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
        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except OSError:
            pass