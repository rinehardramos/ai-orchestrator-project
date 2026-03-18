import pytest
from fastapi.testclient import TestClient
from src.control.coordinator.coordinator import app as coordinator_app

client = TestClient(coordinator_app)

def test_heartbeat():
    payload = {"worker_id": "worker-1"}
    response = client.post("/heartbeat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["worker_id"] == "worker-1"
    assert "timestamp" in data

def test_health_report():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "message" in data
