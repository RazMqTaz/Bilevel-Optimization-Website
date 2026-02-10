from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from fastapi import BackgroundTasks, WebSocket
import sys, os

sys.path.insert(0, os.path.abspath("SACEProject"))
# from SACEProject.main import main

import sqlite3
import json
import tempfile
import bcrypt

app = FastAPI()

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
            data TEXT NOT NULL
        )
    """
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash BLOB NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()

def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

def verify_password(password: str, password_hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash)

class RegisterRequest(BaseModel):
    username: str
    email: EmailStr | None = None
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


@app.post("/submit_json")
def submit_json(payload: dict, background_tasks: BackgroundTasks) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    conn.execute(
        "INSERT INTO submissions (type, data) VALUES (?, ?)",
        ("json", json.dumps(payload)),
    )
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

    # Run SACE in background to avoid blocking API
    def run_sace_job(batch_config):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp_file:
            json.dump(batch_config, tmp_file)
            tmp_file.flush()
            # main(tmp_file.name)
        
    background_tasks.add_task(run_sace_job, batch_json)
    return {"email": email, "message": "Job submitted successfully and will be processed."}

@app.get("/get_submissions")
def get_submissions() -> dict:
    conn = get_db()
    cursor = conn.execute('SELECT * FROM submissions')
    rows = cursor.fetchall()
    conn.close()
    
    submissions_list = []
    for row in rows:
        submissions_list.append({
            "id": row["id"],
            "type": row["type"],
            "data": json.loads(row["data"])
        })
    
    return {"submissions": submissions_list}


@app.post("/register")
def register(req: RegisterRequest) -> dict:
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

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

    return {"message": "Login ok", "user": {"id": row["id"], "username": row["username"]}}
