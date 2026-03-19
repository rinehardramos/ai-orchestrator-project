from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import httpx

app = FastAPI(title="Model Selector Service")

class ModelInfo(BaseModel):
    provider: str
    model_name: str
    max_tokens: int
    latency_ms: int
    capabilities: list

# Placeholder model registry (in real life, query provider APIs)
MODEL_REGISTRY = [
    ModelInfo(provider="openai", model_name="gpt-4o", max_tokens=128000, latency_ms=200, capabilities=["code", "reasoning"]),
    ModelInfo(provider="anthropic", model_name="claude-3-opus", max_tokens=100000, latency_ms=300, capabilities=["text", "summarization"]),
    ModelInfo(provider="google", model_name="gemini-1.5-pro", max_tokens=2000000, latency_ms=400, capabilities=["code", "reasoning", "multimodal"]),
]

def select_model(task_type: str, required_tokens: int) -> ModelInfo:
    # Simple selection: first model that satisfies token budget and supports the task type
    for model in MODEL_REGISTRY:
        if model.max_tokens >= required_tokens and task_type in model.capabilities:
            return model
    # Fallback to first model
    return MODEL_REGISTRY[0]

class SelectionRequest(BaseModel):
    task_type: str
    required_tokens: int

@app.post("/select")
async def select(request: SelectionRequest):
    model = select_model(request.task_type, request.required_tokens)
    return model.model_dump()
