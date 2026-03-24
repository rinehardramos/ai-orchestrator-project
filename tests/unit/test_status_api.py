import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch, AsyncMock
import asyncio

app = FastAPI()
from src.web.api.status import status_router
app.include_router(status_router)
client = TestClient(app)


def test_status_endpoint_exists():
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_status_returns_expected_keys():
    resp = client.get("/api/status")
    data = resp.json()
    assert "workers" in data


def test_status_structure():
    resp = client.get("/api/status")
    data = resp.json()
    if "temporal" in data:
        assert "status" in data["temporal"]
    if "workers" in data:
        assert isinstance(data["workers"], list)
