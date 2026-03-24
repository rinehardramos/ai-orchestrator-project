import os
import json
import time
import logging
from typing import Dict, Optional, List, Any

from src.genesis.diagnostics.models import (
    HealthStatus,
    HealthResult,
    ServiceType,
    DiagnosisReport,
    RemediationStep,
    RemediationAction,
    ActionResult,
    AgentObservation,
    AgentPlan,
)
from src.genesis.diagnostics.health_checker import HealthChecker
from src.genesis.diagnostics.remediator import Remediator
from src.genesis.diagnostics.tools import AgentTools

logger = logging.getLogger("DiagnosticAgent")

SYSTEM_PROMPT = """You are a site reliability engineer (SRE) agent. Your job is to diagnose and fix infrastructure issues autonomously.

CAPABILITIES:
- check_service_status(service_name) -> Get systemd/docker status
- read_logs(service_name, lines=100) -> Fetch service logs
- read_metrics() -> Get CPU, memory, disk usage
- list_docker_containers() -> List all Docker containers
- check_port(host, port) -> Verify TCP port availability
- http_health(url) -> HTTP health check

RULES:
1. Always verify after acting
2. Maximum 3 remediation attempts per issue
3. Prefer least invasive fixes first (restart before rebuild)
4. Document every action taken
5. Escalate to human if unable to fix after 3 attempts

OUTPUT FORMAT (JSON only):
{
  "diagnosis": "Brief explanation of what's wrong",
  "root_cause": "The underlying cause",
  "remediation_steps": [
    {
      "action": "restart_service",
      "target": "temporal",
      "description": "Restart Temporal server",
      "params": {}
    }
  ],
  "verification_steps": ["Check Temporal TCP port", "Check Temporal health endpoint"],
  "rollback_plan": "If restart fails, check logs for config errors",
  "confidence": 0.85
}

Analyze the provided system state and output ONLY valid JSON."""


class DiagnosticAgent:
    """
    Autonomous diagnostic agent that uses OpenRouter LLM for reasoning.
    Implements: OBSERVE -> PLAN -> ACT -> VERIFY -> REFLECT loop.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        diag_config = self.config.get("genesis", {}).get("diagnostic", {})
        self.model = diag_config.get("model", "anthropic/claude-3.5-sonnet")
        self.fallback_model = diag_config.get("fallback_model", "openai/gpt-4o")
        self.max_iterations = diag_config.get("max_iterations", 3)
        self.verify_delay_sec = diag_config.get("verify_delay_sec", 5)
        self.timeout_sec = diag_config.get("timeout_sec", 120)
        
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        
        self.health_checker = HealthChecker(config)
        self.remediator = Remediator(config)
        self.tools = AgentTools(config)
        
        self._current_model = self.model

    def set_model(self, model: str):
        self._current_model = model
        logger.info(f"Diagnostic model set to: {model}")

    def get_model(self) -> str:
        return self._current_model

    def _call_openrouter(self, messages: List[Dict], model: str = None) -> Optional[str]:
        model = model or self._current_model
        
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY not set")
            return None
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ai-orchestrator",
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.1,
        }
        
        try:
            import requests
            resp = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60,
            )
            
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenRouter error: {resp.status_code} - {resp.text}")
                
                if model != self.fallback_model:
                    logger.info(f"Trying fallback model: {self.fallback_model}")
                    return self._call_openrouter(messages, self.fallback_model)
                
                return None
        except Exception as e:
            logger.error(f"OpenRouter request failed: {e}")
            return None

    def _observe(self, services: List[ServiceType] = None) -> AgentObservation:
        observation = AgentObservation()
        
        observation.health_results = self.health_checker.run_full_diagnosis(services).health_results
        
        unhealthy_services = [
            h.service.value for h in observation.health_results
            if h.status == HealthStatus.UNHEALTHY
        ]
        
        for service in unhealthy_services:
            log_result = self.tools.read_logs(service, lines=50)
            observation.logs[service] = log_result.get("logs", "")[:2000]
            
            status = self.tools.check_service_status(service)
            observation.service_statuses[service] = status.get("status", "unknown")
        
        observation.metrics = self.tools.read_metrics()
        
        return observation

    def _plan(self, observation: AgentObservation) -> Optional[AgentPlan]:
        state_description = self._format_observation(observation)
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this system state:\n\n{state_description}"},
        ]
        
        response = self._call_openrouter(messages)
        
        if not response:
            logger.error("Failed to get plan from LLM")
            return None
        
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                plan_data = json.loads(response[json_start:json_end])
            else:
                plan_data = json.loads(response)
            
            steps = []
            for step_data in plan_data.get("remediation_steps", []):
                action_str = step_data.get("action", "no_action")
                try:
                    action = RemediationAction(action_str)
                except ValueError:
                    action = RemediationAction.NO_ACTION
                
                steps.append(RemediationStep(
                    action=action,
                    target=step_data.get("target", ""),
                    params=step_data.get("params", {}),
                    description=step_data.get("description", ""),
                    rollback_command=step_data.get("rollback_command"),
                ))
            
            return AgentPlan(
                diagnosis=plan_data.get("diagnosis", ""),
                root_cause=plan_data.get("root_cause", ""),
                remediation_steps=steps,
                verification_steps=plan_data.get("verification_steps", []),
                rollback_plan=plan_data.get("rollback_plan"),
                confidence=plan_data.get("confidence", 0.0),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return None

    def _act(self, steps: List[RemediationStep]) -> List[ActionResult]:
        results = []
        
        for step in steps:
            if step.action == RemediationAction.NO_ACTION:
                continue
            
            result = self.remediator.execute_step(step)
            results.append(result)
            
            if result.success:
                logger.info(f"Action succeeded: {step.description}")
            else:
                logger.warning(f"Action failed: {step.description} - {result.error}")
        
        return results

    def _verify(self, observation: AgentObservation) -> bool:
        time.sleep(self.verify_delay_sec)
        
        new_observation = self._observe([h.service for h in observation.health_results])
        
        unhealthy = [
            h for h in new_observation.health_results
            if h.status == HealthStatus.UNHEALTHY
        ]
        
        return len(unhealthy) == 0

    def _format_observation(self, observation: AgentObservation) -> str:
        lines = ["=== SYSTEM STATE ===\n"]
        
        lines.append("HEALTH CHECKS:")
        for h in observation.health_results:
            status_icon = "✅" if h.status == HealthStatus.HEALTHY else "❌"
            lines.append(f"  {status_icon} {h.service.value}: {h.status.value}")
            if h.error:
                lines.append(f"     Error: {h.error}")
        
        if observation.service_statuses:
            lines.append("\nSERVICE STATUSES:")
            for service, status in observation.service_statuses.items():
                lines.append(f"  {service}: {status}")
        
        if observation.logs:
            lines.append("\nRECENT LOGS (unhealthy services):")
            for service, logs in observation.logs.items():
                lines.append(f"  --- {service} ---")
                lines.append(logs[:500])
        
        if observation.metrics:
            lines.append("\nSYSTEM METRICS:")
            m = observation.metrics
            if "error" not in m:
                lines.append(f"  CPU: {m.get('cpu_percent', 'N/A')}%")
                lines.append(f"  Memory: {m.get('memory', {}).get('percent', 'N/A')}%")
                lines.append(f"  Disk: {m.get('disk', {}).get('percent', 'N/A')}%")
        
        return "\n".join(lines)

    def diagnose_only(self, services: List[ServiceType] = None) -> DiagnosisReport:
        start_time = time.time()
        
        observation = self._observe(services)
        
        issues = [
            f"{h.service.value}: {h.error}"
            for h in observation.health_results
            if h.status == HealthStatus.UNHEALTHY
        ]
        
        total_ms = (time.time() - start_time) * 1000
        
        return DiagnosisReport(
            success=len(issues) == 0,
            services_checked=[h.service for h in observation.health_results],
            health_results=observation.health_results,
            issues_found=issues,
            model_used=self._current_model,
            total_duration_ms=total_ms,
        )

    def diagnose_and_fix(
        self, services: List[ServiceType] = None, dry_run: bool = False
    ) -> DiagnosisReport:
        start_time = time.time()
        
        if dry_run:
            self.remediator.set_dry_run(True)
        
        all_actions_taken = []
        iterations = 0
        
        for iteration in range(self.max_iterations):
            iterations = iteration + 1
            logger.info(f"[Iteration {iterations}] Starting diagnostic cycle...")
            
            observation = self._observe(services)
            
            unhealthy = [
                h for h in observation.health_results
                if h.status == HealthStatus.UNHEALTHY
            ]
            
            if not unhealthy:
                logger.info("All services healthy!")
                break
            
            plan = self._plan(observation)
            
            if not plan:
                logger.warning("Failed to generate remediation plan")
                break
            
            if not plan.remediation_steps:
                logger.info("No remediation steps proposed")
                break
            
            actions = self._act(plan.remediation_steps)
            all_actions_taken.extend(actions)
            
            if self._verify(observation):
                logger.info("Remediation successful!")
                break
            
            logger.warning(f"Iteration {iterations} did not fix all issues, continuing...")
        
        final_observation = self._observe(services)
        total_ms = (time.time() - start_time) * 1000
        
        needs_human = any(
            h.status == HealthStatus.UNHEALTHY
            for h in final_observation.health_results
        )
        
        return DiagnosisReport(
            success=not needs_human,
            services_checked=[h.service for h in final_observation.health_results],
            health_results=final_observation.health_results,
            issues_found=[
                f"{h.service.value}: {h.error}"
                for h in final_observation.health_results
                if h.status == HealthStatus.UNHEALTHY
            ],
            actions_taken=all_actions_taken,
            needs_human=needs_human,
            iterations=iterations,
            model_used=self._current_model,
            total_duration_ms=total_ms,
        )
