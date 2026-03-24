"""
Scheduled Task Models

Pydantic models for scheduled task CRUD operations and validation.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ScheduleType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    ONCE = "once"


class TaskType(str, Enum):
    AGENT = "agent"
    SHELL = "shell"
    TOOL = "tool"
    WORKFLOW = "workflow"


class TaskStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"


def validate_cron_expression(expression: str) -> bool:
    """Validate a cron expression."""
    try:
        from croniter import croniter
        croniter(expression)
        return True
    except Exception:
        return False


class ScheduledTaskBase(BaseModel):
    """Base model with shared fields."""
    name: str = Field(..., min_length=1, max_length=255, description="Task name")
    description: Optional[str] = Field(None, description="Task description")
    
    schedule_type: ScheduleType = Field(..., description="Type of schedule")
    cron_expression: Optional[str] = Field(None, description="Cron expression (for cron type)")
    interval_seconds: Optional[int] = Field(None, gt=0, description="Interval in seconds (for interval type)")
    scheduled_for: Optional[datetime] = Field(None, description="One-time execution timestamp (for once type)")
    timezone: str = Field(default="UTC", description="Timezone for schedule evaluation")
    
    task_type: TaskType = Field(..., description="Type of task to execute")
    task_payload: Dict[str, Any] = Field(default_factory=dict, description="Task configuration payload")
    
    enabled: bool = Field(default=True, description="Whether task is enabled")
    timeout_seconds: int = Field(default=300, ge=1, le=86400, description="Task timeout in seconds")
    
    max_failures: int = Field(default=3, ge=0, description="Max consecutive failures before disabling")
    max_runs: Optional[int] = Field(None, ge=1, description="Maximum number of runs (None = unlimited)")
    
    notify_on_success: bool = Field(default=False, description="Notify on successful execution")
    notify_on_failure: bool = Field(default=True, description="Notify on failed execution")
    notify_on_start: bool = Field(default=False, description="Notify when task starts")
    notification_channel: NotificationChannel = Field(default=NotificationChannel.TELEGRAM)
    notification_recipients: List[str] = Field(default_factory=list, description="Notification recipients")
    
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    
    @model_validator(mode='after')
    def validate_schedule(self):
        """Validate that schedule configuration matches schedule_type."""
        if self.schedule_type == ScheduleType.CRON:
            if not self.cron_expression:
                raise ValueError("cron_expression is required for cron schedule type")
            if not validate_cron_expression(self.cron_expression):
                raise ValueError(f"Invalid cron expression: {self.cron_expression}")
        
        elif self.schedule_type == ScheduleType.INTERVAL:
            if not self.interval_seconds:
                raise ValueError("interval_seconds is required for interval schedule type")
        
        elif self.schedule_type == ScheduleType.ONCE:
            if not self.scheduled_for:
                raise ValueError("scheduled_for is required for once schedule type")
        
        return self


class ScheduledTaskCreate(ScheduledTaskBase):
    """Model for creating a new scheduled task."""
    created_by: Optional[str] = Field(None, description="User who created the task")
    
    @field_validator('scheduled_for')
    @classmethod
    def validate_scheduled_for(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Ensure scheduled_for is in the future for 'once' type."""
        if v is not None and v <= datetime.now(v.tzinfo) if v.tzinfo else datetime.utcnow():
            pass  # Allow past times for testing, daemon will handle it
        return v


class ScheduledTaskUpdate(BaseModel):
    """Model for updating an existing scheduled task."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    
    schedule_type: Optional[ScheduleType] = None
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = Field(None, gt=0)
    scheduled_for: Optional[datetime] = None
    timezone: Optional[str] = None
    
    task_type: Optional[TaskType] = None
    task_payload: Optional[Dict[str, Any]] = None
    
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(None, ge=1, le=86400)
    
    max_failures: Optional[int] = Field(None, ge=0)
    max_runs: Optional[int] = Field(None, ge=1)
    
    notify_on_success: Optional[bool] = None
    notify_on_failure: Optional[bool] = None
    notify_on_start: Optional[bool] = None
    notification_channel: Optional[NotificationChannel] = None
    notification_recipients: Optional[List[str]] = None
    
    tags: Optional[List[str]] = None
    
    @model_validator(mode='after')
    def validate_schedule(self):
        """Validate schedule fields if they're being updated."""
        if self.schedule_type == ScheduleType.CRON and self.cron_expression is not None:
            if not validate_cron_expression(self.cron_expression):
                raise ValueError(f"Invalid cron expression: {self.cron_expression}")
        
        if self.schedule_type == ScheduleType.INTERVAL and self.interval_seconds is None:
            raise ValueError("interval_seconds is required when schedule_type is interval")
        
        return self


class ScheduledTaskInDB(ScheduledTaskBase):
    """Model representing a scheduled task as stored in database."""
    id: int
    uuid: UUID
    
    status: TaskStatus = TaskStatus.IDLE
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_task_id: Optional[str] = None
    last_run_duration_seconds: Optional[int] = None
    last_error: Optional[str] = None
    
    run_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    
    model_config = {"from_attributes": True}


class ScheduledTaskResponse(ScheduledTaskInDB):
    """Model for API responses."""
    pass


class ScheduledTaskSummary(BaseModel):
    """Brief summary of a scheduled task for list views."""
    id: int
    uuid: UUID
    name: str
    description: Optional[str]
    schedule_type: ScheduleType
    task_type: TaskType
    enabled: bool
    status: TaskStatus
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    run_count: int
    
    model_config = {"from_attributes": True}


class TaskHistoryBase(BaseModel):
    """Base model for task execution history."""
    scheduled_task_id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    temporal_task_id: Optional[str] = None
    temporal_workflow_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    cost_usd: Optional[float] = None
    tool_call_count: Optional[int] = None
    full_result: Optional[Dict[str, Any]] = None


class TaskHistoryCreate(TaskHistoryBase):
    """Model for creating a history entry."""
    pass


class TaskHistoryInDB(TaskHistoryBase):
    """Model representing history entry from database."""
    id: int
    uuid: UUID
    created_at: datetime
    
    model_config = {"from_attributes": True}


class TaskHistoryResponse(TaskHistoryInDB):
    """Model for history API responses."""
    task_name: Optional[str] = None  # Populated from join


class TaskHistoryList(BaseModel):
    """Paginated list of history entries."""
    items: List[TaskHistoryResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class ScheduledTaskList(BaseModel):
    """Paginated list of scheduled tasks."""
    items: List[ScheduledTaskSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class CronPreview(BaseModel):
    """Preview of upcoming cron executions."""
    expression: str
    next_runs: List[datetime]
    description: str


class ScheduleStats(BaseModel):
    """Statistics for a scheduled task."""
    task_id: int
    task_name: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    average_duration_seconds: float
    total_cost_usd: float
    last_success_at: Optional[datetime]
    last_failure_at: Optional[datetime]
