import pytest
from unittest.mock import patch, MagicMock
import socket

from src.genesis.diagnostics.models import (
    HealthStatus,
    HealthResult,
    ServiceType,
    DiagnosisReport,
    RemediationAction,
    RemediationStep,
    ActionResult,
    AgentObservation,
    AgentPlan,
)


class TestHealthResult:
    def test_healthy_result(self):
        result = HealthResult(
            service=ServiceType.TEMPORAL,
            status=HealthStatus.HEALTHY,
            latency_ms=12.5,
        )
        assert result.service == ServiceType.TEMPORAL
        assert result.status == HealthStatus.HEALTHY
        assert result.latency_ms == 12.5
        assert result.error is None

    def test_unhealthy_result(self):
        result = HealthResult(
            service=ServiceType.QDRANT,
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )
        assert result.status == HealthStatus.UNHEALTHY
        assert result.error == "Connection refused"


class TestDiagnosisReport:
    def test_to_telegram_summary_all_healthy(self):
        report = DiagnosisReport(
            success=True,
            services_checked=[ServiceType.TEMPORAL, ServiceType.REDIS],
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY, latency_ms=10),
                HealthResult(service=ServiceType.REDIS, status=HealthStatus.HEALTHY, latency_ms=5),
            ],
            model_used="claude-3.5-sonnet",
        )
        summary = report.to_telegram_summary()
        
        assert "System Diagnosis Report" in summary
        assert "Healthy:" in summary
        assert "temporal" in summary.lower()
        assert "redis" in summary.lower()
        assert "Unhealthy:" not in summary

    def test_to_telegram_summary_with_issues(self):
        report = DiagnosisReport(
            success=False,
            services_checked=[ServiceType.TEMPORAL, ServiceType.QDRANT],
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY, latency_ms=10),
                HealthResult(service=ServiceType.QDRANT, status=HealthStatus.UNHEALTHY, error="Timeout"),
            ],
            issues_found=["qdrant: Timeout"],
            model_used="claude-3.5-sonnet",
        )
        summary = report.to_telegram_summary()
        
        assert "Unhealthy:" in summary
        assert "qdrant" in summary.lower()
        assert "Timeout" in summary


class TestRemediationStep:
    def test_restart_step(self):
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target="temporal",
            description="Restart Temporal server",
        )
        assert step.action == RemediationAction.RESTART_SERVICE
        assert step.target == "temporal"
        assert step.rollback_command is None

    def test_step_with_rollback(self):
        step = RemediationStep(
            action=RemediationAction.EXECUTE_SHELL,
            target="system",
            params={"command": "docker restart temporal"},
            rollback_command="docker start temporal",
        )
        assert step.rollback_command == "docker start temporal"


class TestActionResult:
    def test_successful_action(self):
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target="redis",
        )
        result = ActionResult(
            step=step,
            success=True,
            output="redis\n",
            duration_ms=1500.0,
        )
        assert result.success is True
        assert result.error is None

    def test_failed_action(self):
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target="nonexistent",
        )
        result = ActionResult(
            step=step,
            success=False,
            error="No such service",
        )
        assert result.success is False
        assert result.error == "No such service"


class TestAgentObservation:
    def test_observation(self):
        obs = AgentObservation(
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY),
            ],
            logs={"temporal": "2024-01-01 INFO Starting..."},
            metrics={"cpu_percent": 25.0},
        )
        assert len(obs.health_results) == 1
        assert "temporal" in obs.logs
        assert obs.metrics["cpu_percent"] == 25.0


class TestAgentPlan:
    def test_plan(self):
        plan = AgentPlan(
            diagnosis="Temporal is unreachable",
            root_cause="Docker container stopped",
            remediation_steps=[
                RemediationStep(
                    action=RemediationAction.RESTART_SERVICE,
                    target="temporal",
                )
            ],
            verification_steps=["Check port 7233"],
            confidence=0.9,
        )
        assert plan.diagnosis == "Temporal is unreachable"
        assert len(plan.remediation_steps) == 1
        assert plan.confidence == 0.9
