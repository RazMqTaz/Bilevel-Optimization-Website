from typing import Any, Dict, Optional
from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, EmailStr
from io import StringIO
import sys, os, asyncio

sys.path.insert(0, os.path.abspath("SACEProject"))
from SACEProject.main import main

import sqlite3
import json
import tempfile
import bcrypt

app = FastAPI()

active_connections: Dict[int, WebSocket] = {}
job_outputs: Dict[int, str] = {}


def get_db():
    conn = sqlite3.connect("submissions.db")
    conn.row_factory = sqlite3.Row  # This makes rows accessible as dictionaries
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


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, password_hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash)


class RegisterRequest(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TextEntry(BaseModel):
    text: str


class JsonSubmission(BaseModel):
    data: Dict[str, Any]


@app.post("/add_text")
def add_text(entry: TextEntry) -> dict:
    conn = get_db()
    entry_json = json.dumps(entry.model_dump())
    conn.execute(
        "INSERT INTO submissions (type, data) VALUES (?, ?)", ("text", entry_json)
    )
    conn.commit()
    conn.close()
    return {"message": "text entry appended successfully"}


def run_sace_job(batch_config, job_id) -> None:
    import sys
    from io import StringIO
    
    # Initialize output buffer for this job
    job_outputs[job_id] = ""
    
    # Capture only stdout (not stderr - that's just warnings)
    old_stdout = sys.stdout
    
    # Create a custom writer that updates job_outputs in real-time
    class OutputCapture(StringIO):
        def write(self, s):
            super().write(s)
            if job_id in job_outputs:
                job_outputs[job_id] += s
            # Also print to terminal
            old_stdout.write(s)
            old_stdout.flush()
            self.flush()
            return len(s)
        
        def flush(self):
            super().flush()
    
    sys.stdout = OutputCapture()
    # Don't redirect stderr - let warnings go to terminal only

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
            json.dump(batch_config, tmp_file)
            tmp_file.flush()
            
            # Force unbuffered output
            import os
            os.environ['PYTHONUNBUFFERED'] = '1'
            
            main(tmp_file.name)

        # Mark job as complete in database
        conn = get_db()
        conn.execute("UPDATE submissions SET status='complete' WHERE id=?", (job_id,))
        conn.commit()
        conn.close()

    except Exception as e:
        error_msg = f"\n[ERROR] Job {job_id} failed: {str(e)}\n"
        job_outputs[job_id] += error_msg
        old_stdout.write(error_msg)  # Also print error to terminal
        
        # Mark job as failed in database
        conn = get_db()
        conn.execute("UPDATE submissions SET status='failed' WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        
    finally:
        # Restore stdout
        sys.stdout = old_stdout


@app.post("/submit_json")
def submit_json(payload: dict, background_tasks: BackgroundTasks) -> dict:
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

    # Mark job as running
    conn = get_db()
    conn.execute("UPDATE submissions SET status='running' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

    background_tasks.add_task(run_sace_job, batch_json, job_id)
    return {
        "job_id": job_id,
        "email": email,
        "message": "Job submitted successfully and will be processed.",
    }


@app.get("/job_output/{job_id}")
def get_job_output(job_id: int):
    """Get current output for a job"""
    output = job_outputs.get(job_id, "")
    
    # Check status
    conn = get_db()
    row = conn.execute(
        "SELECT status FROM submissions WHERE id=?", (job_id,)
    ).fetchone()
    conn.close()
    
    status = row["status"] if row else "unknown"
    
    return {
        "output": output,
        "status": status
    }


@app.websocket("/ws/job/{job_id}")
async def websocket_job_output(websocket: WebSocket, job_id: int):
    await websocket.accept()
    active_connections[job_id] = websocket

    try:
        # Check if job already has output
        if job_id in job_outputs:
            await websocket.send_text(job_outputs[job_id])
            await websocket.send_json({"status": "complete"})
            return
        
        # Poll for output while job is running
        last_position = 0
        while True:
            await asyncio.sleep(0.5)

            # Check if any new output
            if job_id in job_outputs:
                output = job_outputs[job_id]

                # Send new output
                if len(output) > last_position:
                    new_output = output[last_position:]
                    await websocket.send_text(new_output)
                    last_position = len(output)
                
                # Check if job is complete
                conn = get_db()
                row = conn.execute(
                    "SELECT status FROM submissions WHERE id=?", (job_id,)
                ).fetchone()
                conn.close()
                
                if row and row['status'] in ['complete', 'failed']:
                    await websocket.send_json({"status": row['status']})
                    break
                    
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for job {job_id}")
    finally:
        if job_id in active_connections:
            del active_connections[job_id]


@app.get("/get_submissions")
def get_submissions() -> dict:
    conn = get_db()
    cursor = conn.execute("SELECT * FROM submissions")
    rows = cursor.fetchall()
    conn.close()

    submissions_list = []
    for row in rows:
        submissions_list.append(
            {"id": row["id"], "type": row["type"], "data": json.loads(row["data"]), "status": row["status"]}
        )

    return {"submissions": submissions_list}


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