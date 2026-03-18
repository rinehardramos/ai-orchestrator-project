import pytest
from fastapi.testclient import TestClient
from src.control.dispatcher.dispatcher import app as dispatcher_app

client = TestClient(dispatcher_app)

def test_dispatch_nlp():
    payload = {
        "task_id": "test1",
        "type": "nlp",
        "priority": 1,
        "payload": {"data": "example"}
    }
    response = client.post("/dispatch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["dispatched_to"] == "nlp_worker"
    assert data["task_id"] == "test1"

def test_dispatch_default():
    payload = {
        "task_id": "test2",
        "type": "unknown",
        "priority": 0,
        "payload": {}
    }
    response = client.post("/dispatch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["dispatched_to"] == "default_worker"
