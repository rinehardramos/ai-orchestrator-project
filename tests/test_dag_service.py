import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Mock psycopg2 before importing the app so it doesn't need a live DB
mock_psycopg2 = MagicMock()
with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
    from src.control.dag.dag_service import app as dag_app

# In-memory store to simulate DB state during tests
_dag_store = {}

def make_mock_conn(store):
    """Creates a context-manager-compatible mock connection backed by the in-memory store."""
    import json as _json

    mock_cur = MagicMock()

    def execute_side_effect(query, params=None):
        q = query.strip().upper()
        if q.startswith("INSERT"):
            dag_id, definition = params
            if dag_id in store:
                raise mock_psycopg2.IntegrityError("duplicate key")
            store[dag_id] = _json.loads(definition)
            mock_cur.rowcount = 1
        elif q.startswith("SELECT"):
            dag_id = params[0]
            row = store.get(dag_id)
            mock_cur.fetchone.return_value = (row,) if row is not None else None
        elif q.startswith("DELETE"):
            dag_id = params[0]
            existed = dag_id in store
            store.pop(dag_id, None)
            mock_cur.rowcount = 1 if existed else 0
        elif "CREATE TABLE" in q:
            pass

    mock_cur.execute.side_effect = execute_side_effect
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


@pytest.fixture(autouse=True)
def reset_store():
    _dag_store.clear()
    yield


def test_create_get_delete_dag():
    dag_id = "testdag"
    definition = {"tasks": [{"id": "t1", "depends_on": []}]}

    with patch("src.control.dag.dag_service.get_conn", side_effect=lambda: make_mock_conn(_dag_store)), \
         patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
        client = TestClient(dag_app)

        # Create
        resp = client.post("/dags", json={"id": dag_id, "definition": definition})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "created"

        # Get
        resp = client.get(f"/dags/{dag_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == dag_id

        # Delete
        resp = client.delete(f"/dags/{dag_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "deleted"

        # Verify deletion returns 404
        resp = client.get(f"/dags/{dag_id}")
        assert resp.status_code == 404
