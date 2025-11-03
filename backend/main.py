from typing import Any, Dict
from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
import json

app = FastAPI()


def get_db():
    conn = sqlite3.connect('submissions.db')
    conn.row_factory = sqlite3.Row  # This makes rows accessible as dictionaries
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            data TEXT NOT NULL
        )
    ''')
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
        'INSERT INTO submissions (type, data) VALUES (?, ?)',
        ('text', entry_json)
    )
    conn.commit()
    conn.close()
    return {"message": "text entry appended successfully"}


@app.post("/submit_json")
def submit_json(submission: JsonSubmission) -> dict:
    conn = get_db()
    submission_json = json.dumps(submission.model_dump())
    conn.execute(
        'INSERT INTO submissions (type, data) VALUES (?, ?)',
        ('json', submission_json)
    )
    conn.commit()
    conn.close()
    return {
        "message": "JSON submitted successfully",
    }


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


@app.get("/solve_problem")
def solve_problem() -> dict:
    conn = get_db()
    cursor = conn.execute("SELECT * FROM submissions WHERE type = 'json'")
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) == 0:
        return {"result": "error"}
    
    results = []
    for row in rows:
        submission_data = json.loads(row["data"])
        email = submission_data["data"]["email"]
        problem_str = submission_data["data"]["problem"]
        try:
            result = eval(submission_data["data"]["problem"])
        except Exception:
            result = "Error"
        results.append({"email": email, "result": result})
    return {"results": results}
