import pytest
from unittest.mock import patch, MagicMock, Mock
import json

from src.genesis.diagnostics.diagnostic_agent import DiagnosticAgent
from src.genesis.diagnostics.models import (
    HealthStatus,
    HealthResult,
    ServiceType,
    RemediationAction,
    RemediationStep,
)


class TestDiagnosticAgent:
    @pytest.fixture
    def agent(self):
        with patch("src.genesis.diagnostics.diagnostic_agent.HealthChecker") as mock_hc, \
             patch("src.genesis.diagnostics.diagnostic_agent.Remediator") as mock_rem, \
             patch("src.genesis.diagnostics.diagnostic_agent.AgentTools") as mock_tools:
            
            mock_hc_instance = Mock()
            mock_hc_instance.run_full_diagnosis.return_value.health_results = []
            mock_hc.return_value = mock_hc_instance
            
            agent = DiagnosticAgent({
                "genesis": {
                    "diagnostic": {
                        "model": "test-model",
                        "fallback_model": "fallback-model",
                        "max_iterations": 2,
                    }
                }
            })
            return agent

    def test_set_and_get_model(self, agent):
        assert agent.get_model() == "test-model"
        
        agent.set_model("new-model")
        assert agent.get_model() == "new-model"

    def test_diagnose_only_healthy(self, agent):
        from src.genesis.diagnostics.models import DiagnosisReport, HealthResult
        
        with patch.object(agent, '_observe') as mock_observe:
            mock_observe.return_value = MagicMock(
                health_results=[
                    HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY),
                    HealthResult(service=ServiceType.REDIS, status=HealthStatus.HEALTHY),
                ],
                logs={},
                metrics={},
                service_statuses={},
            )
            
            report = agent.diagnose_only()
            
            assert report.success is True
            assert len(report.issues_found) == 0

    def test_diagnose_only_unhealthy(self, agent):
        from src.genesis.diagnostics.models import DiagnosisReport, HealthResult
        
        with patch.object(agent, '_observe') as mock_observe:
            mock_observe.return_value = MagicMock(
                health_results=[
                    HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY),
                    HealthResult(service=ServiceType.QDRANT, status=HealthStatus.UNHEALTHY, error="Timeout"),
                ],
                logs={},
                metrics={},
                service_statuses={},
            )
            
            report = agent.diagnose_only()
            
            assert report.success is False
            assert len(report.issues_found) == 1
            assert "qdrant" in report.issues_found[0].lower()

    def test_call_openrouter_success(self, agent):
        agent.api_key = "test-key"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        
        with patch("requests.post", return_value=mock_response):
            result = agent._call_openrouter([{"role": "user", "content": "test"}])
            
            assert result == "Test response"

    def test_call_openrouter_fallback(self, agent):
        agent.api_key = "test-key"
        
        mock_fail = Mock()
        mock_fail.status_code = 500
        mock_fail.text = "Error"
        
        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "choices": [{"message": {"content": "Fallback response"}}]
        }
        
        with patch("requests.post", side_effect=[mock_fail, mock_success]):
            result = agent._call_openrouter([{"role": "user", "content": "test"}])
            
            assert result == "Fallback response"

    def test_call_openrouter_no_api_key(self, agent):
        agent.api_key = None
        
        result = agent._call_openrouter([{"role": "user", "content": "test"}])
        
        assert result is None

    def test_plan_parses_json_response(self, agent):
        agent.api_key = "test-key"
        
        llm_response = json.dumps({
            "diagnosis": "Service down",
            "root_cause": "Container crashed",
            "remediation_steps": [
                {"action": "restart_service", "target": "temporal", "description": "Restart Temporal"}
            ],
            "verification_steps": ["Check port 7233"],
            "confidence": 0.9
        })
        
        with patch.object(agent, '_call_openrouter', return_value=llm_response):
            observation = MagicMock(
                health_results=[
                    HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.UNHEALTHY)
                ],
                logs={},
                metrics={},
                service_statuses={},
            )
            
            plan = agent._plan(observation)
            
            assert plan is not None
            assert plan.diagnosis == "Service down"
            assert plan.root_cause == "Container crashed"
            assert len(plan.remediation_steps) == 1
            assert plan.confidence == 0.9

    def test_act_executes_steps(self, agent):
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target="temporal",
        )
        
        with patch.object(agent.remediator, 'execute_step') as mock_exec:
            from src.genesis.diagnostics.models import ActionResult
            mock_exec.return_value = ActionResult(
                step=step,
                success=True,
                output="OK",
            )
            
            results = agent._act([step])
            
            assert len(results) == 1
            assert results[0].success is True

    def test_verify_checks_health(self, agent):
        observation = MagicMock(
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.UNHEALTHY)
            ]
        )
        
        with patch.object(agent, '_observe') as mock_observe:
            mock_observe.return_value = MagicMock(
                health_results=[
                    HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY)
                ]
            )
            
            result = agent._verify(observation)
            
            assert result is True

    def test_diagnose_and_fix_success(self, agent):
        healthy_obs = MagicMock(
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.HEALTHY)
            ],
            logs={},
            metrics={},
            service_statuses={},
        )
        
        unhealthy_obs = MagicMock(
            health_results=[
                HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.UNHEALTHY)
            ],
            logs={},
            metrics={},
            service_statuses={},
        )
        
        with patch.object(agent, '_observe') as mock_observe, \
             patch.object(agent, '_plan') as mock_plan, \
             patch.object(agent, '_act') as mock_act, \
             patch.object(agent, '_verify') as mock_verify:
            
            mock_observe.side_effect = [unhealthy_obs, healthy_obs]
            
            mock_plan.return_value = MagicMock(
                remediation_steps=[
                    RemediationStep(action=RemediationAction.RESTART_SERVICE, target="temporal")
                ]
            )
            
            mock_act.return_value = []
            mock_verify.return_value = True
            
            report = agent.diagnose_and_fix()
            
            assert report.success is True

    def test_diagnose_and_fix_needs_human(self, agent):
        with patch.object(agent, '_observe') as mock_observe, \
             patch.object(agent, '_plan') as mock_plan, \
             patch.object(agent, '_act') as mock_act, \
             patch.object(agent, '_verify') as mock_verify:
            
            mock_observe.return_value = MagicMock(
                health_results=[
                    HealthResult(service=ServiceType.TEMPORAL, status=HealthStatus.UNHEALTHY)
                ],
                logs={},
                metrics={},
                service_statuses={},
            )
            
            mock_plan.return_value = MagicMock(
                remediation_steps=[
                    RemediationStep(action=RemediationAction.RESTART_SERVICE, target="temporal")
                ]
            )
            
            mock_act.return_value = []
            mock_verify.return_value = False
            
            report = agent.diagnose_and_fix()
            
            assert report.success is False
            assert report.needs_human is True
