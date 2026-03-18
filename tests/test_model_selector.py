import pytest
from fastapi.testclient import TestClient
from src.control.model_selector.selector import app as selector_app

client = TestClient(selector_app)

def test_select_model_code():
    resp = client.post("/select", json={"task_type": "code", "required_tokens": 1000})
    assert resp.status_code == 200
    assert resp.json()["model_name"] == "gpt-4o"

def test_select_model_text():
    resp = client.post("/select", json={"task_type": "text", "required_tokens": 50000})
    assert resp.status_code == 200
    assert resp.json()["model_name"] == "claude-3-opus"

def test_select_model_fallback():
    # If no capability matches, it falls back to first model (gpt-4o)
    resp = client.post("/select", json={"task_type": "nonexistent", "required_tokens": 1000})
    assert resp.status_code == 200
    assert resp.json()["model_name"] == "gpt-4o"
