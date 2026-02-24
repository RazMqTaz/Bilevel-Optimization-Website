from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
import sys, os, asyncio

import sqlite3
import json
import bcrypt
from redis import Redis

from backend.celery_worker import celery_app, run_sace_job

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI()


# ── Database ──────────────────────────────────────────────────────────────────


def get_db():
    conn = sqlite3.connect("submissions.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
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
    conn.commit()
    conn.close()


init_db()


# ── Auth helpers ──────────────────────────────────────────────────────────────


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, password_hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash)


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


@app.post("/add_text")
def add_text(entry: TextEntry) -> dict:
    conn = get_db()
    conn.execute(
        "INSERT INTO submissions (type, data) VALUES (?, ?)",
        ("text", json.dumps(entry.model_dump())),
    )
    conn.commit()
    conn.close()
    return {"message": "text entry appended successfully"}


@app.post("/submit_json")
def submit_json(payload: dict) -> dict:
    """Submit a SACE job — enqueues it on Celery via Redis."""
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO submissions (type, data, status) VALUES (?, ?, ?)",
        ("json", json.dumps(payload), "pending"),
    )
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()

    submission_data = payload["data"]
    email = submission_data.get("email", "unknown")

    batch_json = {
        "experiment_name": submission_data.get("experiment_name", f"SACE_User_{email}"),
        "problems": submission_data.get("problems", []),
        "algorithms": submission_data.get("algorithms", []),
        "settings": submission_data.get("settings", {}),
    }

    # Dispatch to Celery worker
    run_sace_job.delay(batch_json, job_id)

    return {
        "job_id": job_id,
        "email": email,
        "message": "Job submitted successfully and will be processed.",
    }


@app.get("/job_output/{job_id}")
def get_job_output(job_id: int):
    """HTTP polling endpoint — returns current accumulated output."""
    output = redis_client.get(f"job_output:{job_id}") or ""

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM submissions WHERE id=?", (job_id,)
    ).fetchone()
    conn.close()

    status = row["status"] if row else "unknown"
    return {"output": output, "status": status}


@app.get("/job_stream/{job_id}")
async def job_stream_sse(job_id: int):
    """Server-Sent Events endpoint for real-time streaming."""

    async def event_generator():
        pubsub = redis_client.pubsub()
        pubsub.subscribe(f"job_stream:{job_id}")

        # First, send any output that already exists
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
                    yield f"data: {json.dumps({'output': chunk})}\n\n"
                else:
                    # Send keepalive to prevent timeout
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.1)
        finally:
            pubsub.unsubscribe()
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.websocket("/ws/job/{job_id}")
async def websocket_job_output(websocket: WebSocket, job_id: int):
    """WebSocket endpoint for real-time streaming (alternative to SSE)."""
    await websocket.accept()

    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"job_stream:{job_id}")

    try:
        # Send existing output first
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
                    status = row["status"] if row else "complete"
                    await websocket.send_json({"status": status})
                    break
                await websocket.send_text(chunk)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for job {job_id}")
    finally:
        pubsub.unsubscribe()
        pubsub.close()


@app.get("/get_submissions")
def get_submissions() -> dict:
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

    return {
        "message": "Login ok",
        "user": {"id": row["id"], "username": row["username"]},
    }
