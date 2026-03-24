import pytest
from fastapi.testclient import TestClient
from src.web.api.config import config_router
from fastapi import FastAPI
import os
import yaml

app = FastAPI()
app.include_router(config_router)
client = TestClient(app)


def test_get_routing():
    resp = client.get("/api/config/routing")
    assert resp.status_code == 200
    data = resp.json()
    assert "planning" in data


def test_get_models():
    resp = client.get("/api/config/models")
    assert resp.status_code == 200
    models = resp.json()
    assert isinstance(models, list)
    assert len(models) > 0
    assert any("gemini" in m["id"] for m in models)


def test_get_specializations():
    resp = client.get("/api/config/specializations")
    assert resp.status_code == 200
    specs = resp.json()
    assert "general" in specs
    assert "coding" in specs


def test_get_agent_defaults():
    resp = client.get("/api/config/agent-defaults")
    assert resp.status_code == 200
    defaults = resp.json()
    assert "max_tool_calls" in defaults
    assert "max_cost_usd" in defaults


def test_get_infrastructure():
    resp = client.get("/api/config/infrastructure")
    assert resp.status_code == 200
    infra = resp.json()
    assert "active_environment" in infra
    assert "environments" in infra


def test_get_cluster():
    resp = client.get("/api/config/cluster")
    assert resp.status_code == 200
    nodes = resp.json()
    assert isinstance(nodes, list)
    assert any(n["name"] == "genesis" for n in nodes)


def test_put_routing():
    original = client.get("/api/config/routing").json()
    updated = dict(original)
    updated["planning"]["model"] = "test-model"
    
    resp = client.put("/api/config/routing", json={"routing": updated})
    assert resp.status_code == 200
    
    restored = dict(original)
    resp = client.put("/api/config/routing", json={"routing": restored})
    assert resp.status_code == 200
    
    final = client.get("/api/config/routing").json()
    assert final["planning"]["model"] == original["planning"]["model"]


def test_put_agent_defaults():
    original = client.get("/api/config/agent-defaults").json()
    updated = dict(original)
    updated["max_tool_calls"] = 999
    
    resp = client.put("/api/config/agent-defaults", json={"agent_defaults": updated})
    assert resp.status_code == 200
    
    resp = client.put("/api/config/agent-defaults", json={"agent_defaults": original})
    assert resp.status_code == 200
