import pytest
from unittest.mock import patch, MagicMock, Mock
import socket

from src.genesis.diagnostics.health_checker import HealthChecker
from src.genesis.diagnostics.models import HealthStatus, ServiceType


class TestHealthChecker:
    @pytest.fixture
    def checker(self):
        with patch("src.genesis.diagnostics.health_checker.load_settings") as mock_settings:
            mock_settings.return_value = {
                "temporal": {"host": "localhost", "port": 7233},
                "qdrant": {"host": "localhost", "port": 6333},
                "redis": {"host": "localhost", "port": 6379},
                "lmstudio": {"host": "localhost", "port": 1234},
            }
            return HealthChecker()

    def test_check_tcp_healthy(self, checker):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = Mock(return_value=None)
            mock_conn.return_value.__exit__ = Mock(return_value=None)
            
            result = checker.check_tcp("localhost", 7233)
            
            assert result.status == HealthStatus.HEALTHY
            assert result.latency_ms is not None

    def test_check_tcp_timeout(self, checker):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.side_effect = socket.timeout()
            
            result = checker.check_tcp("localhost", 7233)
            
            assert result.status == HealthStatus.UNHEALTHY
            assert "timeout" in result.error.lower()

    def test_check_tcp_connection_refused(self, checker):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError()
            
            result = checker.check_tcp("localhost", 7233)
            
            assert result.status == HealthStatus.UNHEALTHY
            assert "refused" in result.error.lower()

    def test_check_http_healthy(self, checker):
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            result = checker.check_http("http://localhost:6333/collections")
            
            assert result.status == HealthStatus.HEALTHY

    def test_check_http_unexpected_status(self, checker):
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            result = checker.check_http("http://localhost:6333/collections")
            
            assert result.status == HealthStatus.UNHEALTHY
            assert "500" in result.error

    def test_check_http_timeout(self, checker):
        import requests
        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            
            result = checker.check_http("http://localhost:6333/collections")
            
            assert result.status == HealthStatus.UNHEALTHY

    def test_check_http_connection_error(self, checker):
        import requests
        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()
            
            result = checker.check_http("http://localhost:6333/collections")
            
            assert result.status == HealthStatus.UNHEALTHY

    def test_check_temporal(self, checker):
        with patch.object(checker, 'check_tcp') as mock_tcp:
            from src.genesis.diagnostics.models import HealthResult
            mock_tcp.return_value = HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.HEALTHY,
                latency_ms=10.0,
            )
            
            result = checker.check_temporal()
            
            assert result.service == ServiceType.TEMPORAL
            mock_tcp.assert_called_once()

    def test_check_qdrant(self, checker):
        with patch.object(checker, 'check_http') as mock_http:
            from src.genesis.diagnostics.models import HealthResult
            mock_http.return_value = HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.HEALTHY,
                latency_ms=10.0,
            )
            
            result = checker.check_qdrant()
            
            assert result.service == ServiceType.QDRANT

    def test_check_redis(self, checker):
        with patch.object(checker, 'check_tcp') as mock_tcp:
            from src.genesis.diagnostics.models import HealthResult
            mock_tcp.return_value = HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.HEALTHY,
                latency_ms=5.0,
            )
            
            result = checker.check_redis()
            
            assert result.service == ServiceType.REDIS

    def test_run_full_diagnosis_all_healthy(self, checker):
        with patch.object(checker, 'check_service') as mock_check:
            from src.genesis.diagnostics.models import HealthResult
            mock_check.side_effect = [
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY),
                HealthResult(service=ServiceType.QDRANT, status=HealthStatus.HEALTHY),
                HealthResult(service=ServiceType.REDIS, status=HealthStatus.HEALTHY),
                HealthResult(service=ServiceType.LITELLM, status=HealthStatus.HEALTHY),
            ]
            
            report = checker.run_full_diagnosis()
            
            assert report.success is True
            assert len(report.issues_found) == 0
            assert len(report.services_checked) == 4

    def test_run_full_diagnosis_with_failures(self, checker):
        with patch.object(checker, 'check_service') as mock_check:
            from src.genesis.diagnostics.models import HealthResult
            mock_check.side_effect = [
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY),
                HealthResult(service=ServiceType.QDRANT, status=HealthStatus.UNHEALTHY, error="Timeout"),
                HealthResult(service=ServiceType.REDIS, status=HealthStatus.HEALTHY),
                HealthResult(service=ServiceType.LITELLM, status=HealthStatus.UNHEALTHY, error="Connection refused"),
            ]
            
            report = checker.run_full_diagnosis()
            
            assert report.success is False
            assert len(report.issues_found) == 2

    def test_check_service_unknown(self, checker):
        from src.genesis.diagnostics.models import ServiceType
        result = checker.check_service(ServiceType.POSTGRES)
        
        assert result.status == HealthStatus.UNKNOWN
