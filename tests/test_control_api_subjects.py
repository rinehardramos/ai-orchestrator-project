import sqlite3, os, tempfile, pytest
from pathlib import Path

def test_task_subjects_table_created(tmp_path, monkeypatch):
    """_ensure_task_subjects_table creates the table if absent."""
    db_path = tmp_path / "offline_queue.db"
    monkeypatch.setenv("OFFLINE_QUEUE_DB", str(db_path))

    # Import after setting env so _OFFLINE_DB picks up tmp_path
    import importlib, sys
    sys.modules.pop("src.control.api.main", None)
    import src.control.api.main as api_main

    api_main._ensure_task_subjects_table()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_subjects'")
    assert cur.fetchone() is not None
    conn.close()


from fastapi.testclient import TestClient

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_QUEUE_DB", str(tmp_path / "offline_queue.db"))
    monkeypatch.setenv("CONTROL_API_KEY", "test-key")
    import importlib, sys
    sys.modules.pop("src.control.api.main", None)
    import src.control.api.main as api_main
    return TestClient(api_main.app), api_main

HDR = {"X-Control-API-Key": "test-key"}

def test_post_subject(client):
    tc, _ = client
    r = tc.post("/tasks/subjects", json={
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }, headers=HDR)
    assert r.status_code == 201
    assert r.json()["subject"] == "EOS Report Gmail Draft"

def test_get_subjects_fuzzy(client):
    tc, _ = client
    tc.post("/tasks/subjects", json={
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }, headers=HDR)
    r = tc.get("/tasks/subjects?q=EOS report", headers=HDR)
    assert r.status_code == 200
    data = r.json()
    assert len(data["matches"]) >= 1
    assert data["matches"][0]["subject"] == "EOS Report Gmail Draft"

def test_get_subjects_no_match(client):
    tc, _ = client
    r = tc.get("/tasks/subjects?q=nonexistent task xyz", headers=HDR)
    assert r.status_code == 200
    assert r.json()["matches"] == []
