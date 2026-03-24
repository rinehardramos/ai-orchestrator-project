import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.control.scaler.scaler import app as scaler_app

client = TestClient(scaler_app)

@patch("src.control.scaler.scaler.subprocess.run")
def test_scale_service_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    
    resp = client.post("/scale", json={"service_name": "worker", "replicas": 3})
    assert resp.status_code == 200
    assert resp.json()["status"] == "scaled"
    assert resp.json()["replicas"] == 3
    
    # Check if correct command was called
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "docker" in args
    assert "compose" in args
    assert "--scale" in args
    assert "worker=3" in args

@patch("src.control.scaler.scaler.subprocess.run")
def test_scale_service_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="Something went wrong")
    
    resp = client.post("/scale", json={"service_name": "worker", "replicas": 3})
    assert resp.status_code == 500
    assert "Compose scaling failed" in resp.json()["detail"]
