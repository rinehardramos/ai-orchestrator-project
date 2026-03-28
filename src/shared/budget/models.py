from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from decimal import Decimal


@dataclass
class UsageRecord:
    task_id: str
    provider: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    workflow_id: Optional[str] = None
    step_id: Optional[str] = None
    pipeline_stage: Optional[str] = None
    task_type: Optional[str] = None
    metadata: Optional[dict] = field(default_factory=dict)


@dataclass
class BudgetCheck:
    provider: str
    provider_spent: float
    provider_limit: float
    provider_pct: float
    model_id: Optional[str] = None
    model_spent: Optional[float] = None
    model_limit: Optional[float] = None
    model_pct: Optional[float] = None
    should_alert: bool = False
    alert_type: Optional[str] = None


@dataclass
class ProviderBudget:
    provider: str
    budget_limit_usd: Decimal
    current_balance_usd: Optional[Decimal] = None
    threshold_pct: Decimal = Decimal("0.80")
    alert_interval_tasks: int = 5
    pull_from_api: bool = False
    api_key_env: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None


@dataclass
class ModelPricing:
    provider: str
    model_id: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal
    is_override: bool = False
    source: str = "hardcoded"
    effective_date: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None


@dataclass
class PipelineStageStats:
    pipeline_stage: str
    avg_tokens_per_occurrence: Decimal
    avg_cost_per_occurrence: Decimal
    frequency_per_task: Decimal
    total_occurrences: int
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TaskPattern:
    task_type: str
    task_complexity: str
    avg_steps: int
    avg_total_tokens: int
    avg_cost_usd: Decimal
    sample_count: int
    last_updated: datetime = field(default_factory=datetime.utcnow)
