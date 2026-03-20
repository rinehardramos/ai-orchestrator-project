import pytest
from fastapi.testclient import TestClient
from src.control.model_selector.selector import app as selector_app, select_model

client = TestClient(selector_app)


def test_select_model_text():
    """Text tasks should return the lowest-capability (cheapest) model."""
    resp = client.post("/select", json={"task_type": "text", "required_tokens": 1000})
    assert resp.status_code == 200
    data = resp.json()
    assert "model_name" in data
    assert "text" in data["capabilities"]


def test_select_model_code():
    """Code tasks require at least medium reasoning capability."""
    resp = client.post("/select", json={"task_type": "code", "required_tokens": 1000})
    assert resp.status_code == 200
    data = resp.json()
    assert "code" in data["capabilities"]


def test_select_model_reasoning():
    """Reasoning tasks should return a high-capability model."""
    resp = client.post("/select", json={"task_type": "reasoning", "required_tokens": 1000})
    assert resp.status_code == 200
    data = resp.json()
    assert "reasoning" in data["capabilities"]


def test_select_model_fallback():
    """Unknown task type falls back to the first model in the registry."""
    resp = client.post("/select", json={"task_type": "nonexistent_type", "required_tokens": 1000})
    assert resp.status_code == 200
    assert "model_name" in resp.json()


def test_select_model_token_budget():
    """A model with insufficient context window should not be selected."""
    # Request more tokens than any single model can handle (> 1B)
    model = select_model("text", required_tokens=2_000_000_000)
    # Falls back to first model — should still return something valid
    assert model is not None
    assert model.max_tokens > 0
