import pytest
import os
from unittest.mock import patch, MagicMock
from src.cnc.orchestrator.backup_manager import BackupManager


@pytest.fixture
def mock_backup_manager(tmpdir):
    with patch("src.cnc.orchestrator.backup_manager.load_settings") as mock_load_settings:
        mock_load_settings.return_value = {
            "qdrant": {"host": "localhost", "port": 6333},
            "postgres": {"host": "localhost", "port": 5432, "user": "temporal", "db": "temporal"},
        }
        manager = BackupManager()
        manager.backup_dir = str(tmpdir)
        yield manager


def test_backup_manager_init(mock_backup_manager):
    assert os.path.exists(mock_backup_manager.backup_dir)


@patch("src.cnc.orchestrator.backup_manager.requests.get")
@patch("src.cnc.orchestrator.backup_manager.requests.post")
def test_backup_qdrant_success(mock_post, mock_get, mock_backup_manager, tmpdir):
    # Mock: list collections
    list_collections_resp = MagicMock()
    list_collections_resp.json.return_value = {
        "result": {"collections": [{"name": "knowledge_base"}]}
    }
    list_collections_resp.raise_for_status = MagicMock()

    # Mock: snapshot created
    snapshot_resp = MagicMock()
    snapshot_resp.json.return_value = {"result": {"name": "snapshot_001"}}
    snapshot_resp.raise_for_status = MagicMock()

    # Mock: snapshot listed (ready)
    list_snaps_resp = MagicMock()
    list_snaps_resp.json.return_value = {"result": [{"name": "snapshot_001"}]}
    list_snaps_resp.raise_for_status = MagicMock()

    # Mock: snapshot download (streaming)
    dl_resp = MagicMock()
    dl_resp.iter_content.return_value = [b"data"]
    dl_resp.raise_for_status = MagicMock()

    mock_get.side_effect = [list_collections_resp, list_snaps_resp, dl_resp]
    mock_post.return_value = snapshot_resp

    result = mock_backup_manager.backup_qdrant()

    assert result is True
    mock_post.assert_called_once()


@patch("src.cnc.orchestrator.backup_manager.requests.get")
def test_backup_qdrant_connection_error(mock_get, mock_backup_manager):
    import requests as req
    mock_get.side_effect = req.exceptions.ConnectionError("refused")
    result = mock_backup_manager.backup_qdrant()
    assert result is False


@patch("src.cnc.orchestrator.backup_manager.subprocess.run")
def test_backup_temporal_success(mock_run, mock_backup_manager):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    result = mock_backup_manager.backup_temporal()
    assert result is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "pg_dump" in cmd


@patch("src.cnc.orchestrator.backup_manager.subprocess.run")
def test_backup_temporal_pg_dump_failure(mock_run, mock_backup_manager):
    mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
    result = mock_backup_manager.backup_temporal()
    assert result is False


@patch("src.cnc.orchestrator.backup_manager.subprocess.run")
def test_backup_temporal_pg_dump_not_found(mock_run, mock_backup_manager):
    mock_run.side_effect = FileNotFoundError("pg_dump not found")
    result = mock_backup_manager.backup_temporal()
    assert result is False


@patch("src.cnc.orchestrator.backup_manager.BackupManager.backup_qdrant", return_value=True)
@patch("src.cnc.orchestrator.backup_manager.BackupManager.backup_temporal", return_value=True)
def test_run_all_backups(mock_temporal, mock_qdrant, mock_backup_manager):
    results = mock_backup_manager.run_all_backups()
    mock_qdrant.assert_called_once()
    mock_temporal.assert_called_once()
    assert results == {"qdrant": True, "temporal": True}
