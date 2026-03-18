import pytest
from fastapi.testclient import TestClient
from src.control.dag.dag_service import app as dag_app

client = TestClient(dag_app)

def test_create_get_delete_dag():
    dag_id = "testdag"
    definition = {"tasks": [{"id": "t1", "depends_on": []}]}
    # Create
    resp = client.post("/dags", json={"id": dag_id, "definition": definition})
    assert resp.status_code == 200
    assert resp.json()["status"] == "created"
    # Get
    resp = client.get(f"/dags/{dag_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == dag_id
    assert data["definition"] == definition
    # Delete
    resp = client.delete(f"/dags/{dag_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    # Verify deletion
    resp = client.get(f"/dags/{dag_id}")
    assert resp.status_code == 404
