from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Placeholder db is just a list for now
texts = []

class TextEntry(BaseModel):
    text: str

@app.post("/add_text")
def add_text(entry: TextEntry) -> dict:
    texts.append(entry)
    return {"message" : "text entry appended successfully"}

@app.get("/get_texts")
def get_texts() -> dict:
    return {"texts" : texts}