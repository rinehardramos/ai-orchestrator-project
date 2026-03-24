import socket
import asyncio
import time
import logging
from typing import Dict, List, Optional
import requests

from src.genesis.diagnostics.models import (
    HealthStatus,
    HealthResult,
    ServiceType,
    DiagnosisReport,
)
from src.config import load_settings

logger = logging.getLogger("HealthChecker")


class HealthChecker:
    """
    Standalone health checker using only TCP/HTTP probes.
    No external client library dependencies.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or load_settings()
        self._service_configs = self._build_service_configs()

    def _build_service_configs(self) -> Dict[ServiceType, Dict]:
        configs = {}
        
        temporal_cfg = self.config.get("temporal", {})
        configs[ServiceType.TEMPORAL] = {
            "host": temporal_cfg.get("host", "localhost"),
            "port": temporal_cfg.get("port", 7233),
            "type": "tcp",
        }
        
        qdrant_cfg = self.config.get("qdrant", {})
        configs[ServiceType.QDRANT] = {
            "host": qdrant_cfg.get("host", "localhost"),
            "port": qdrant_cfg.get("port", 6333),
            "type": "http",
            "path": "/collections",
        }
        
        redis_cfg = self.config.get("redis", {})
        configs[ServiceType.REDIS] = {
            "host": redis_cfg.get("host", "localhost"),
            "port": redis_cfg.get("port", 6379),
            "type": "tcp",
        }
        
        lmstudio_cfg = self.config.get("lmstudio", {})
        configs[ServiceType.LITELLM] = {
            "host": lmstudio_cfg.get("host", "localhost"),
            "port": lmstudio_cfg.get("port", 1234),
            "type": "http",
            "path": "/v1/models",
        }
        
        return configs

    def check_tcp(self, host: str, port: int, timeout: float = 3.0) -> HealthResult:
        start = time.time()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                latency_ms = (time.time() - start) * 1000
                return HealthResult(
                    service=ServiceType.SYSTEM,
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency_ms,
                    details={"host": host, "port": port},
                )
        except socket.timeout:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error="Connection timeout",
                details={"host": host, "port": port},
            )
        except ConnectionRefusedError:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error="Connection refused",
                details={"host": host, "port": port},
            )
        except OSError as e:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error=str(e),
                details={"host": host, "port": port},
            )

    def check_http(
        self, url: str, timeout: float = 5.0, expected_status: int = 200
    ) -> HealthResult:
        start = time.time()
        try:
            resp = requests.get(url, timeout=timeout)
            latency_ms = (time.time() - start) * 1000
            
            if resp.status_code == expected_status:
                return HealthResult(
                    service=ServiceType.SYSTEM,
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency_ms,
                    details={"url": url, "status_code": resp.status_code},
                )
            else:
                return HealthResult(
                    service=ServiceType.SYSTEM,
                    status=HealthStatus.UNHEALTHY,
                    error=f"Unexpected status: {resp.status_code}",
                    latency_ms=latency_ms,
                    details={"url": url, "status_code": resp.status_code},
                )
        except requests.exceptions.Timeout:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error="HTTP timeout",
                details={"url": url},
            )
        except requests.exceptions.ConnectionError:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error="Connection failed",
                details={"url": url},
            )
        except Exception as e:
            return HealthResult(
                service=ServiceType.SYSTEM,
                status=HealthStatus.UNHEALTHY,
                error=str(e),
                details={"url": url},
            )

    def check_temporal(self) -> HealthResult:
        cfg = self._service_configs.get(ServiceType.TEMPORAL, {})
        result = self.check_tcp(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 7233),
        )
        result.service = ServiceType.TEMPORAL
        return result

    def check_qdrant(self) -> HealthResult:
        cfg = self._service_configs.get(ServiceType.QDRANT, {})
        host = cfg.get("host", "localhost")
        port = cfg.get("port", 6333)
        url = f"http://{host}:{port}{cfg.get('path', '/collections')}"
        
        result = self.check_http(url)
        result.service = ServiceType.QDRANT
        return result

    def check_redis(self) -> HealthResult:
        cfg = self._service_configs.get(ServiceType.REDIS, {})
        result = self.check_tcp(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 6379),
        )
        result.service = ServiceType.REDIS
        return result

    def check_litellm(self) -> HealthResult:
        cfg = self._service_configs.get(ServiceType.LITELLM, {})
        host = cfg.get("host", "localhost")
        port = cfg.get("port", 1234)
        url = f"http://{host}:{port}{cfg.get('path', '/v1/models')}"
        
        result = self.check_http(url)
        result.service = ServiceType.LITELLM
        return result

    def check_worker(self, host: str = None, port: int = 22) -> HealthResult:
        remote_cfg = self.config.get("remote_worker", {})
        host = host or remote_cfg.get("host", "localhost")
        port = remote_cfg.get("port", 22)
        
        result = self.check_tcp(host, port, timeout=5.0)
        result.service = ServiceType.WORKER
        return result

    def run_full_diagnosis(
        self, services: Optional[List[ServiceType]] = None
    ) -> DiagnosisReport:
        start_time = time.time()
        
        if services is None:
            services = [
                ServiceType.TEMPORAL,
                ServiceType.QDRANT,
                ServiceType.REDIS,
                ServiceType.LITELLM,
            ]
        
        health_results = []
        issues = []
        
        for service in services:
            result = self.check_service(service)
            health_results.append(result)
            
            if result.status == HealthStatus.UNHEALTHY:
                issues.append(f"{service.value}: {result.error}")
        
        total_ms = (time.time() - start_time) * 1000
        
        return DiagnosisReport(
            success=len(issues) == 0,
            services_checked=services,
            health_results=health_results,
            issues_found=issues,
            total_duration_ms=total_ms,
        )

    def check_service(self, service: ServiceType) -> HealthResult:
        checkers = {
            ServiceType.TEMPORAL: self.check_temporal,
            ServiceType.QDRANT: self.check_qdrant,
            ServiceType.REDIS: self.check_redis,
            ServiceType.LITELLM: self.check_litellm,
            ServiceType.WORKER: self.check_worker,
        }
        
        checker = checkers.get(service)
        if checker:
            return checker()
        
        return HealthResult(
            service=service,
            status=HealthStatus.UNKNOWN,
            error=f"No checker implemented for {service.value}",
        )
