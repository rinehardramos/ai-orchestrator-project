import pytest
from fastapi.testclient import TestClient
from src.web.api.tools import tools_router
from fastapi import FastAPI
import os

app = FastAPI()
app.include_router(tools_router)
client = TestClient(app)


def test_list_tools():
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)


def test_get_tool():
    resp = client.get("/api/tools/shell")
    assert resp.status_code == 200
    tool = resp.json()
    assert tool["name"] == "shell"
    assert tool["type"] == "code"


def test_get_nonexistent_tool():
    resp = client.get("/api/tools/nonexistent_tool_xyz")
    assert resp.status_code == 404


def test_create_tool_without_credentials():
    resp = client.post("/api/tools", json={
        "name": "test_tool_temp",
        "type": "test",
        "module": "src.tools_catalog.test.dummy",
        "enabled": False,
        "config": {"key": "value"}
    })
    assert resp.status_code == 200
    
    client.delete("/api/tools/test_tool_temp")


def test_create_tool_with_credentials_rejected_without_db():
    resp = client.post("/api/tools", json={
        "name": "test_tool_with_creds",
        "type": "test",
        "module": "src.tools_catalog.test.dummy",
        "enabled": False,
        "config": {},
        "credentials": {"api_key": "secret123"}
    })
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"].lower()


def test_update_tool_with_credentials_rejected_without_db():
    resp = client.put("/api/tools/shell", json={
        "credentials": {"secret_key": "supersecret"}
    })
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"].lower()


def test_credentials_masked_in_list():
    resp = client.get("/api/tools")
    tools = resp.json()
    for tool in tools:
        if "credentials" in tool and tool["credentials"]:
            for key, val in tool["credentials"].items():
                assert val == "••••••"


def test_enable_disable_tool():
    resp = client.patch("/api/tools/shell/enable")
    assert resp.status_code == 200
    
    resp = client.get("/api/tools/shell")
    assert resp.json()["enabled"] == True
    
    resp = client.patch("/api/tools/shell/disable")
    assert resp.status_code == 200
    
    resp = client.get("/api/tools/shell")
    assert resp.json()["enabled"] == False
    
    client.patch("/api/tools/shell/enable")
