import asyncio
import logging
from typing import Optional
from datetime import datetime
from decimal import Decimal

from .models import UsageRecord, BudgetCheck

logger = logging.getLogger(__name__)


class UsageExtractor:
    _context_task_id: dict = {}
    _context_workflow_id: dict = {}
    _context_step_id: dict = {}
    _context_pipeline_stage: dict = {}
    _context_task_type: dict = {}
    
    @classmethod
    def set_context(
        cls,
        task_id: str,
        workflow_id: Optional[str] = None,
        step_id: Optional[str] = None,
        pipeline_stage: Optional[str] = None,
        task_type: Optional[str] = None
    ):
        import contextvars
        cls._current_task_id = contextvars.ContextVar("task_id", default=None)
        cls._current_workflow_id = contextvars.ContextVar("workflow_id", default=None)
        cls._current_step_id = contextvars.ContextVar("step_id", default=None)
        cls._current_pipeline_stage = contextvars.ContextVar("pipeline_stage", default=None)
        cls._current_task_type = contextvars.ContextVar("task_type", default=None)
        
        cls._current_task_id.set(task_id)
        if workflow_id:
            cls._current_workflow_id.set(workflow_id)
        if step_id:
            cls._current_step_id.set(step_id)
        if pipeline_stage:
            cls._current_pipeline_stage.set(pipeline_stage)
        if task_type:
            cls._current_task_type.set(task_type)
    
    @classmethod
    def get_context(cls) -> dict:
        try:
            import contextvars
            return {
                "task_id": getattr(cls, "_current_task_id", contextvars.ContextVar("x", default=None)).get(),
                "workflow_id": getattr(cls, "_current_workflow_id", contextvars.ContextVar("x", default=None)).get(),
                "step_id": getattr(cls, "_current_step_id", contextvars.ContextVar("x", default=None)).get(),
                "pipeline_stage": getattr(cls, "_current_pipeline_stage", contextvars.ContextVar("x", default=None)).get(),
                "task_type": getattr(cls, "_current_task_type", contextvars.ContextVar("x", default=None)).get(),
            }
        except:
            return {}
    
    @staticmethod
    def extract_from_openrouter(response, model: str, cost_usd: float) -> Optional[UsageRecord]:
        try:
            usage = getattr(response, "usage", None)
            if not usage:
                return None
            
            context = UsageExtractor.get_context()
            
            return UsageRecord(
                task_id=context.get("task_id") or "unknown",
                workflow_id=context.get("workflow_id"),
                step_id=context.get("step_id"),
                pipeline_stage=context.get("pipeline_stage"),
                provider="openrouter",
                model_id=model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0),
                completion_tokens=getattr(usage, "completion_tokens", 0),
                total_tokens=getattr(usage, "total_tokens", 0),
                cost_usd=cost_usd,
                task_type=context.get("task_type"),
            )
        except Exception as e:
            logger.error(f"Failed to extract usage from OpenRouter response: {e}")
            return None
    
    @staticmethod
    def extract_from_google(response, model: str, cost_usd: float) -> Optional[UsageRecord]:
        try:
            usage = getattr(response, "usage_metadata", None)
            if not usage:
                usage = getattr(response, "usage", None)
            
            if not usage:
                return None
            
            context = UsageExtractor.get_context()
            
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            
            return UsageRecord(
                task_id=context.get("task_id") or "unknown",
                workflow_id=context.get("workflow_id"),
                step_id=context.get("step_id"),
                pipeline_stage=context.get("pipeline_stage"),
                provider="google",
                model_id=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                task_type=context.get("task_type"),
            )
        except Exception as e:
            logger.error(f"Failed to extract usage from Google response: {e}")
            return None
    
    @staticmethod
    def extract_from_anthropic(response, model: str, cost_usd: float) -> Optional[UsageRecord]:
        try:
            usage = getattr(response, "usage", None)
            if not usage:
                return None
            
            context = UsageExtractor.get_context()
            
            prompt_tokens = getattr(usage, "input_tokens", 0) or 0
            completion_tokens = getattr(usage, "output_tokens", 0) or 0
            
            return UsageRecord(
                task_id=context.get("task_id") or "unknown",
                workflow_id=context.get("workflow_id"),
                step_id=context.get("step_id"),
                pipeline_stage=context.get("pipeline_stage"),
                provider="anthropic",
                model_id=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                task_type=context.get("task_type"),
            )
        except Exception as e:
            logger.error(f"Failed to extract usage from Anthropic response: {e}")
            return None
