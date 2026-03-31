from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
import sys, os, asyncio, uuid

import sqlite3
import json
import bcrypt
from redis import Redis

from backend.celery_worker import celery_app, run_sace_job
from backend.config_validator import validate_config, ConfigValidationError

DB_PATH = os.environ.get("DB_PATH", "submissions.db")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI()

SESSION_TTL = 86400  # 24 hours


# ── Database ──────────────────────────────────────────────────────────────────


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            result_data TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash BLOB NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Lightweight migration for existing DBs: add created_at if missing
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(submissions)").fetchall()]
    if "created_at" not in cols:
        conn.execute("ALTER TABLE submissions ADD COLUMN created_at DATETIME")
        conn.execute(
            "UPDATE submissions SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    init_db()


# ── Auth helpers ──────────────────────────────────────────────────────────────


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, password_hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash)


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Extract and validate session token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ", 1)[1]
    session_data = redis_client.get(f"session:{token}")

    if not session_data:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return json.loads(session_data)


# ── Models ────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TextEntry(BaseModel):
    text: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.post("/register")
def register(req: RegisterRequest) -> dict:
    if len(req.password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters."
        )
    pw_hash = hash_password(req.password)
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (req.username.strip(), req.email, pw_hash),
        )
        conn.commit()
        return {"message": "Account created"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username or email already exists.")
    finally:
        conn.close()


@app.post("/login")
def login(req: LoginRequest) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (req.username.strip(),),
    ).fetchone()
    conn.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = str(uuid.uuid4())
    session_data = json.dumps({"id": row["id"], "username": row["username"]})
    redis_client.setex(f"session:{token}", SESSION_TTL, session_data)

    return {
        "message": "Login ok",
        "token": token,
        "user": {"id": row["id"], "username": row["username"]},
    }


@app.post("/logout")
def logout(user: dict = Depends(get_current_user), authorization: Optional[str] = Header(None)):
    token = authorization.split(" ", 1)[1]
    redis_client.delete(f"session:{token}")
    return {"message": "Logged out"}


@app.post("/submit_json")
def submit_json(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Submit a SACE job — validates config, then enqueues on Celery."""
    submission_data = payload.get("data")
    if not submission_data or not isinstance(submission_data, dict):
        raise HTTPException(status_code=422, detail="Missing or invalid 'data' field.")

    email = submission_data.get("email", "unknown")

    # ── Build the batch config from the submission ──
    batch_json = {
        "experiment_name": submission_data.get("experiment_name", f"SACE_User_{email}"),
        "problems": submission_data.get("problems", []),
        "algorithms": submission_data.get("algorithms", []),
        "settings": submission_data.get("settings", {}),
    }

    # ── VALIDATE before persisting or dispatching ──
    try:
        validated_batch = validate_config(batch_json)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=e.detail)

    # ── Persist the validated config (not the raw payload) ──
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO submissions (user_id, type, data, status) VALUES (?, ?, ?, ?)",
        (user["id"], "json", json.dumps(validated_batch), "pending"),
    )
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # ── Dispatch the validated config to Celery ──
    task = run_sace_job.delay(validated_batch, job_id)
    redis_client.set(f"job_task_id:{job_id}", task.id)

    return {
        "job_id": job_id,
        "email": email,
        "message": "Job submitted successfully and will be processed.",
    }


@app.post("/cancel_job/{job_id}")
def cancel_job(job_id: int, user: dict = Depends(get_current_user)):
    """Cancel a pending or running SACE job."""
    conn = get_db()
    row = conn.execute(
        "SELECT status FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")

    if row["status"] in ("complete", "failed", "cancelled"):
        conn.close()
        return {"message": f"Job already {row['status']}", "status": row["status"]}

    # Set cancellation flag in Redis (worker checks this during cleanup)
    redis_client.set(f"job_cancel:{job_id}", "1", ex=3600)

    # Revoke the Celery task
    task_id = redis_client.get(f"job_task_id:{job_id}")
    if task_id:
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

    # Update DB status
    conn.execute(
        "UPDATE submissions SET status='cancelled' WHERE id=?", (job_id,)
    )
    conn.commit()
    conn.close()

    # Notify any live listeners
    redis_client.publish(f"job_stream:{job_id}", "\n[CANCELLED]\n")

    return {"message": "Job cancelled", "job_id": job_id, "status": "cancelled"}


@app.get("/job_output/{job_id}")
def get_job_output(job_id: int, user: dict = Depends(get_current_user)):
    """HTTP polling endpoint — returns current accumulated output for the user's job."""
    conn = get_db()
    row = conn.execute(
        "SELECT status FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    output = redis_client.get(f"job_output:{job_id}") or ""
    return {"output": output, "status": row["status"]}


@app.get("/job_results/{job_id}")
def get_job_results(job_id: int, user: dict = Depends(get_current_user)):
    """Return parsed CSV result data for a completed job."""
    conn = get_db()
    row = conn.execute(
        "SELECT result_data FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    if row["result_data"]:
        return {"data": row["result_data"]}
    return {"error": "No results found"}


@app.get("/job_stream/{job_id}")
async def job_stream_sse(job_id: int, user: dict = Depends(get_current_user)):
    """Server-Sent Events endpoint for real-time streaming."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        pubsub = redis_client.pubsub()
        pubsub.subscribe(f"job_stream:{job_id}")

        existing = redis_client.get(f"job_output:{job_id}")
        if existing:
            yield f"data: {json.dumps({'output': existing})}\n\n"

        try:
            while True:
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    chunk = msg["data"]
                    if chunk == "\n[DONE]\n":
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break
                    if chunk == "\n[CANCELLED]\n":
                        yield f"data: {json.dumps({'cancelled': True})}\n\n"
                        break
                    yield f"data: {json.dumps({'output': chunk})}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.1)
        finally:
            pubsub.unsubscribe()
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.websocket("/ws/job/{job_id}")
async def websocket_job_output(websocket: WebSocket, job_id: int):
    """WebSocket endpoint for real-time streaming."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    session_data = redis_client.get(f"session:{token}")
    if not session_data:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user = json.loads(session_data)

    conn = get_db()
    row = conn.execute(
        "SELECT id FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()
    conn.close()

    if not row:
        await websocket.close(code=4004, reason="Job not found")
        return

    await websocket.accept()

    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"job_stream:{job_id}")

    try:
        existing = redis_client.get(f"job_output:{job_id}")
        if existing:
            await websocket.send_text(existing)

        while True:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg and msg["type"] == "message":
                chunk = msg["data"]
                if chunk == "\n[DONE]\n":
                    conn = get_db()
                    row = conn.execute(
                        "SELECT status FROM submissions WHERE id=?",
                        (job_id,),
                    ).fetchone()
                    conn.close()
                    await websocket.send_json({"status": row["status"] if row else "complete"})
                    break
                if chunk == "\n[CANCELLED]\n":
                    await websocket.send_json({"status": "cancelled"})
                    break
                await websocket.send_text(chunk)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for job {job_id}")
    finally:
        pubsub.unsubscribe()
        pubsub.close()


@app.get("/my_jobs")
def get_my_jobs(user: dict = Depends(get_current_user)) -> dict:
    """Get all jobs for the authenticated user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, type, data, status, created_at FROM submissions WHERE user_id=? ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return {
        "jobs": [
            {
                "id": r["id"],
                "type": r["type"],
                "data": json.loads(r["data"]),
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@app.delete("/my_jobs/{job_id}")
def delete_my_job(job_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Delete one specific job for the authenticated user."""
    conn = get_db()
    row = conn.execute(
        "SELECT status FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")

    if row["status"] in ("pending", "running"):
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete an active job. Cancel it first, then delete it.",
        )

    conn.execute(
        "DELETE FROM submissions WHERE id=? AND user_id=?",
        (job_id, user["id"]),
    )
    conn.commit()
    conn.close()

    # Clean up related Redis keys for this job id.
    redis_client.delete(
        f"job_output:{job_id}",
        f"job_task_id:{job_id}",
        f"job_cancel:{job_id}",
    )
    return {"message": "Job deleted", "job_id": job_id}


@app.get("/get_submissions")
def get_submissions() -> dict:
    """Admin-style endpoint — consider removing or protecting in production."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM submissions").fetchall()
    conn.close()
    return {
        "submissions": [
            {
                "id": r["id"],
                "type": r["type"],
                "data": json.loads(r["data"]),
                "status": r["status"],
            }
            for r in rows
        ]
    }