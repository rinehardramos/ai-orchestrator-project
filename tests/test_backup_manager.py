import pytest
import os
from unittest.mock import patch, MagicMock
from src.cnc.orchestrator.backup_manager import BackupManager

@pytest.fixture
def mock_backup_manager(tmpdir):
    with patch("src.cnc.orchestrator.backup_manager.load_settings") as mock_load_settings:
        mock_load_settings.return_value = {"qdrant": {"host": "localhost", "port": 6333}}
        manager = BackupManager()
        # Override backup dir to temp directory
        manager.backup_dir = str(tmpdir)
        yield manager

def test_backup_manager_init(mock_backup_manager):
    assert os.path.exists(mock_backup_manager.backup_dir)

@patch("src.cnc.orchestrator.backup_manager.datetime")
def test_backup_qdrant(mock_datetime, mock_backup_manager):
    mock_datetime.datetime.now.return_value.strftime.return_value = "20260318_120000"
    
    result = mock_backup_manager.backup_qdrant()
    
    assert result is True
    # If it were actually writing a file, we could check for it here,
    # but currently it's a mock implementation that just returns True.

@patch("src.cnc.orchestrator.backup_manager.datetime")
def test_backup_temporal(mock_datetime, mock_backup_manager):
    mock_datetime.datetime.now.return_value.strftime.return_value = "20260318_120000"
    
    result = mock_backup_manager.backup_temporal()
    
    assert result is True

@patch("src.cnc.orchestrator.backup_manager.BackupManager.backup_qdrant")
@patch("src.cnc.orchestrator.backup_manager.BackupManager.backup_temporal")
def test_run_all_backups(mock_backup_temporal, mock_backup_qdrant, mock_backup_manager):
    mock_backup_manager.run_all_backups()
    
    mock_backup_qdrant.assert_called_once()
    mock_backup_temporal.assert_called_once()
