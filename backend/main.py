from typing import Any, Dict
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import BackgroundTasks, WebSocket
import sys, os

sys.path.insert(0, os.path.abspath("SACEProject"))
from SACEProject.main import main

import sqlite3
import json
import tempfile

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
    conn.commit()
    conn.close()


init_db()


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
            main(tmp_file.name)
        
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

