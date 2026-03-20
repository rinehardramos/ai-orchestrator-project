import os
import yaml
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Model Selector Service")

_PROFILES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../config/profiles.yaml")
)

# Capability map from profiles.yaml reasoning_capability to selector capabilities
_CAPABILITY_MAP = {
    "low": ["text"],
    "medium": ["text", "code"],
    "high": ["text", "code", "reasoning"],
}


class ModelInfo(BaseModel):
    provider: str
    model_name: str
    max_tokens: int
    latency_ms: int
    capabilities: list


def _load_registry() -> list[ModelInfo]:
    """Load model registry dynamically from config/profiles.yaml."""
    if not os.path.exists(_PROFILES_PATH):
        return []

    with open(_PROFILES_PATH, "r") as f:
        data = yaml.safe_load(f) or {}

    # Rough latency estimate by speed label
    speed_latency = {"ultra_fast": 50, "very_fast": 100, "fast": 200, "slow": 500}

    registry = []
    for m in data.get("models", []):
        speed = m.get("speed", "fast")
        capability = m.get("reasoning_capability", "low")
        registry.append(ModelInfo(
            provider=m.get("provider", "unknown"),
            model_name=m.get("id", "unknown"),
            max_tokens=m.get("context_window", 128000),
            latency_ms=speed_latency.get(speed, 200),
            capabilities=_CAPABILITY_MAP.get(capability, ["text"]),
        ))
    return registry


def select_model(task_type: str, required_tokens: int) -> ModelInfo:
    registry = _load_registry()
    for model in registry:
        if model.max_tokens >= required_tokens and task_type in model.capabilities:
            return model
    # Fallback to first available model
    return registry[0] if registry else ModelInfo(
        provider="google",
        model_name="gemini-2.0-flash-lite",
        max_tokens=1000000,
        latency_ms=50,
        capabilities=["text"],
    )


class SelectionRequest(BaseModel):
    task_type: str
    required_tokens: int


@app.post("/select")
async def select(request: SelectionRequest):
    model = select_model(request.task_type, request.required_tokens)
    return model.model_dump()
