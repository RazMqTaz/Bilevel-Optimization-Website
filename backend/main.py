from typing import Any, Dict
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Placeholder db is just a list for now
submissions = []


class TextEntry(BaseModel):
    text: str


class JsonSubmission(BaseModel):
    data: Dict[str, Any]


@app.post("/add_text")
def add_text(entry: TextEntry) -> dict:
    submissions.append(entry)
    return {"message": "text entry appended successfully"}


@app.post("/submit_json")
def submit_json(submission: JsonSubmission) -> dict:
    submissions.append(submission)
    return {
        "message": "JSON submitted successfully",
    }


@app.get("/get_submissions")
def get_submissions() -> dict:
    return {"submissions": submissions}


@app.get("/solve_problem")
def solve_problem() -> dict:
    if len(submissions) == 0:
        return {"result": "error"}
    results = []
    for submission in submissions:
        email = submission["data"]["email"]
        problem_str = submission["data"]["problem"]
        try:
            result = eval(submission["data"]["problem"])
        except Exception:
            result = "Error"
        results.append({"email": email, "result": result})
    return {"results": results}
