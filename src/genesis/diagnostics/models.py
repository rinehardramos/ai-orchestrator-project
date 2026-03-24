from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


class ServiceType(str, Enum):
    TEMPORAL = "temporal"
    QDRANT = "qdrant"
    REDIS = "redis"
    LITELLM = "litellm"
    WORKER = "worker"
    POSTGRES = "postgres"
    SYSTEM = "system"


class HealthResult(BaseModel):
    service: ServiceType
    status: HealthStatus
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class RemediationAction(str, Enum):
    RESTART_SERVICE = "restart_service"
    FLUSH_CACHE = "flush_cache"
    CLEANUP_LOGS = "cleanup_logs"
    EXECUTE_SHELL = "execute_shell"
    KILL_PROCESS = "kill_process"
    SCALE_UP = "scale_up"
    NOTIFY_HUMAN = "notify_human"
    NO_ACTION = "no_action"


class RemediationStep(BaseModel):
    action: RemediationAction
    target: str
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    rollback_command: Optional[str] = None


class ActionResult(BaseModel):
    step: RemediationStep
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0


class DiagnosisReport(BaseModel):
    success: bool
    services_checked: List[ServiceType] = Field(default_factory=list)
    health_results: List[HealthResult] = Field(default_factory=list)
    issues_found: List[str] = Field(default_factory=list)
    root_cause: Optional[str] = None
    remediation_steps: List[RemediationStep] = Field(default_factory=list)
    actions_taken: List[ActionResult] = Field(default_factory=list)
    needs_human: bool = False
    iterations: int = 0
    model_used: Optional[str] = None
    total_duration_ms: float = 0
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_telegram_summary(self) -> str:
        lines = ["🏥 *System Diagnosis Report*\n"]
        
        healthy = [h for h in self.health_results if h.status == HealthStatus.HEALTHY]
        unhealthy = [h for h in self.health_results if h.status == HealthStatus.UNHEALTHY]
        
        if healthy:
            lines.append("✅ *Healthy:*")
            for h in healthy:
                latency = f" ({h.latency_ms:.0f}ms)" if h.latency_ms else ""
                lines.append(f"  • {h.service.value}{latency}")
        
        if unhealthy:
            lines.append("\n❌ *Unhealthy:*")
            for h in unhealthy:
                lines.append(f"  • {h.service.value}: {h.error or 'unknown error'}")
        
        if self.issues_found:
            lines.append("\n🔍 *Issues Found:*")
            for issue in self.issues_found[:5]:
                lines.append(f"  • {issue}")
        
        if self.actions_taken:
            lines.append("\n🔧 *Actions Taken:*")
            for action in self.actions_taken:
                icon = "✅" if action.success else "❌"
                lines.append(f"  {icon} {action.step.description or action.step.action.value}")
        
        if self.needs_human:
            lines.append("\n⚠️ *Requires human intervention*")
        
        lines.append(f"\n📊 Model: `{self.model_used or 'default'}`")
        lines.append(f"⏱ Iterations: {self.iterations}")
        
        return "\n".join(lines)


class AgentObservation(BaseModel):
    health_results: List[HealthResult] = Field(default_factory=list)
    logs: Dict[str, str] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    service_statuses: Dict[str, str] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    diagnosis: str
    root_cause: str
    remediation_steps: List[RemediationStep] = Field(default_factory=list)
    verification_steps: List[str] = Field(default_factory=list)
    rollback_plan: Optional[str] = None
    confidence: float = 0.0
