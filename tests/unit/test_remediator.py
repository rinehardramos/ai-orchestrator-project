import pytest
from unittest.mock import patch, MagicMock, Mock
import subprocess

from src.genesis.diagnostics.remediator import Remediator
from src.genesis.diagnostics.models import RemediationAction, RemediationStep


class TestRemediator:
    @pytest.fixture
    def remediator(self):
        return Remediator()

    def test_dry_run_mode(self, remediator):
        remediator.set_dry_run(True)
        
        with patch("subprocess.run") as mock_run:
            result = remediator.restart_service("temporal")
            
            assert result.success is True
            assert "DRY RUN" in result.output
            mock_run.assert_not_called()

    def test_restart_service_docker(self, remediator):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="temporal\n", stderr="")
            
            result = remediator.restart_service("temporal")
            
            assert result.success is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "docker" in args
            assert "restart" in args
            assert "temporal" in args

    def test_restart_service_systemd(self, remediator):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="active\n", stderr="")
            
            result = remediator.restart_service("nginx")
            
            assert result.success is True
            args = mock_run.call_args[0][0]
            assert "systemctl" in args
            assert "restart" in args

    def test_restart_service_failure(self, remediator):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="Container not found")
            
            result = remediator.restart_service("nonexistent")
            
            assert result.success is False
            assert result.error is not None

    def test_restart_service_timeout(self, remediator):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker"], timeout=30)
            
            result = remediator.restart_service("temporal")
            
            assert result.success is False
            assert result.error is not None

    def test_flush_cache_redis(self, remediator):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="OK\n", stderr="")
            
            result = remediator.flush_cache("redis")
            
            assert result.success is True
            args = mock_run.call_args[0][0]
            assert "redis-cli" in args
            assert "FLUSHALL" in args

    def test_execute_step_restart(self, remediator):
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target="redis",
            description="Restart Redis",
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="redis\n", stderr="")
            
            result = remediator.execute_step(step)
            
            assert result.success is True
            assert result.step.action == RemediationAction.RESTART_SERVICE
            assert result.step.target == "redis"

    def test_execute_step_flush_cache(self, remediator):
        step = RemediationStep(
            action=RemediationAction.FLUSH_CACHE,
            target="redis",
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="OK\n", stderr="")
            
            result = remediator.execute_step(step)
            
            assert result.success is True

    def test_execute_step_unknown_action(self, remediator):
        step = RemediationStep(
            action=RemediationAction.NO_ACTION,
            target="system",
        )
        
        result = remediator.execute_step(step)
        
        assert result.success is False
        assert "No handler" in result.error

    def test_restart_via_ssh(self, remediator):
        remediator.config = {
            "remote_worker": {
                "user": "testuser",
                "ssh_key_path": "~/.ssh/test_key",
                "port": 22,
            }
        }
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="temporal\n", stderr="")
            
            result = remediator.restart_via_ssh("192.168.1.100", "temporal")
            
            assert result.success is True
            args = mock_run.call_args[0][0]
            assert "ssh" in args
            assert "testuser@192.168.1.100" in " ".join(args)
