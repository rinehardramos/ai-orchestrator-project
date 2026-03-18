import pytest
from fastapi.testclient import TestClient
from src.catalog.catalog import app as catalog_app

client = TestClient(catalog_app)

def test_create_and_get_template():
    tpl = {
        "id": "tpl1",
        "name": "Example Template",
        "description": "A test template",
        "definition": "{\"steps\": []}"
    }
    # Create
    resp = client.post("/templates", json=tpl)
    assert resp.status_code == 200
    assert resp.json()["status"] == "created"
    # Get
    resp = client.get(f"/templates/{tpl['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == tpl["id"]
    assert data["name"] == tpl["name"]
    # Delete
    resp = client.delete(f"/templates/{tpl['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

def test_list_templates():
    # Ensure list returns a list (may be empty)
    resp = client.get("/templates")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
