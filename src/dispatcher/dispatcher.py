from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os

app = FastAPI(title="Task Dispatcher")

class TaskPayload(BaseModel):
    task_id: str
    type: str
    priority: int = 0
    payload: dict

# Simple classification logic (placeholder)
def classify_task(task: TaskPayload) -> str:
    # In a real implementation, this could use LLM or rule‑based logic
    if task.type == "nlp":
        return "nlp_worker"
    if task.type == "data":
        return "data_worker"
    return "default_worker"

@app.post("/dispatch")
async def dispatch(task: TaskPayload):
    worker_pool = classify_task(task)
    # Here we would forward the task to Temporal or a message queue for the selected pool
    # For now we just acknowledge
    return {"dispatched_to": worker_pool, "task_id": task.task_id}
