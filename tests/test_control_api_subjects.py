import sqlite3, os, tempfile, pytest
from pathlib import Path

def test_task_subjects_table_created(tmp_path):
    """_ensure_task_subjects_table creates the table if absent."""
    db_path = tmp_path / "offline_queue.db"
    os.environ["OFFLINE_QUEUE_DB"] = str(db_path)

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
