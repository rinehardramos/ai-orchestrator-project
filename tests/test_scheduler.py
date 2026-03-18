import pytest
import sqlite3
import os
import json
from unittest.mock import patch, MagicMock, AsyncMock
from src.orchestrator.scheduler import TaskScheduler

@pytest.fixture
def mock_scheduler(tmpdir):
    with patch("src.orchestrator.scheduler.load_settings") as mock_settings:
        mock_settings.return_value = {}
        # We patch sqlite3 connect to use a temporary DB for tests
        scheduler = TaskScheduler("dummy-temporal-queue", "dummy-table")
        
        # Override offline DB path to temporary dir
        scheduler.offline_db_path = os.path.join(str(tmpdir), "offline_queue.db")
        scheduler._init_offline_db()
        
        yield scheduler

def test_init_offline_db(mock_scheduler):
    assert os.path.exists(mock_scheduler.offline_db_path)
    
    conn = sqlite3.connect(mock_scheduler.offline_db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='offline_tasks'")
    table_exists = c.fetchone()
    conn.close()
    
    assert table_exists is not None

def test_save_task_offline(mock_scheduler):
    test_id = "test_task_123"
    test_desc = "Test description"
    test_meta = {"key": "value"}
    
    mock_scheduler._save_task_offline(test_id, test_desc, test_meta)
    
    conn = sqlite3.connect(mock_scheduler.offline_db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM offline_tasks WHERE task_id=?", (test_id,))
    row = c.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == test_id
    assert row[1] == test_desc
    assert json.loads(row[2]) == test_meta
    assert row[3] == "QUEUED"

@patch("src.orchestrator.scheduler.TaskScheduler.check_connectivity")
def test_submit_task_preflight_cache(mock_check_conn, mock_scheduler):
    # Setup mock KB
    mock_scheduler.preflight_cache = {}
    test_desc = "deploy aws instance"
    cache_key = test_desc.lower().strip()
    
    with patch("src.memory.knowledge_base.KnowledgeBaseClient") as MockKB:
        mock_kb_instance = MockKB.return_value
        mock_kb_instance.query_similar_issues.return_value = [{"title": "Warning", "score": 0.9}]
        
        # We need to patch input to automatically reply 'y' to proceed anyway
        with patch("builtins.input", return_value="y"):
            # We also need to patch Temporal Client to avoid actual connection
            with patch("src.orchestrator.scheduler.Client.connect", new_callable=AsyncMock) as mock_connect:
                mock_client = AsyncMock()
                mock_connect.return_value = mock_client
                
                import asyncio
                asyncio.run(mock_scheduler.submit_task(test_desc))
                
                # Verify KB was queried
                mock_kb_instance.query_similar_issues.assert_called_once()
                
                # Verify it was cached
                assert cache_key in mock_scheduler.preflight_cache
                assert mock_scheduler.preflight_cache[cache_key] == [{"title": "Warning", "score": 0.9}]

                # Run again with same description, ensure KB is not queried again
                mock_kb_instance.reset_mock()
                asyncio.run(mock_scheduler.submit_task(test_desc))
                mock_kb_instance.query_similar_issues.assert_not_called()
