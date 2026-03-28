import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, date
from decimal import Decimal

from .models import UsageRecord, BudgetCheck
from .usage_extractor import UsageExtractor

logger = logging.getLogger(__name__)


class BudgetTracker:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.redis_client = None
        self.db_pool = None
        self.notifier = None
    
    def initialize(self, redis_client=None, db_pool=None, notifier=None):
        self.redis_client = redis_client
        self.db_pool = db_pool
        self.notifier = notifier
    
    async def record_usage(self, usage: UsageRecord) -> BudgetCheck:
        if self.redis_client:
            try:
                await self._update_redis(usage)
            except Exception as e:
                logger.error(f"Failed to update Redis: {e}")
        
        if self.db_pool:
            try:
                await self._save_to_postgres(usage)
            except Exception as e:
                logger.error(f"Failed to save to Postgres: {e}")
        
        check = await self._check_thresholds(usage)
        
        if check.should_alert and self.notifier:
            await self.notifier.send_budget_alert(check, usage)
        
        return check
    
    def record_usage_sync(self, usage: UsageRecord) -> None:
        """Synchronous method to record usage using sync Redis client."""
        import redis
        
        try:
            sync_redis = redis.Redis(
                host='redis',
                port=6379,
                decode_responses=True
            )
            
            sync_redis.incrbyfloat(f"budget:provider:{usage.provider}:spent", usage.cost_usd)
            sync_redis.incrbyfloat(f"budget:model:{usage.provider}:{usage.model_id}:spent", usage.cost_usd)
            sync_redis.incrby(f"budget:model:{usage.provider}:{usage.model_id}:tokens", usage.total_tokens)
            
            if usage.pipeline_stage:
                sync_redis.incrby(f"budget:pipeline:{usage.pipeline_stage}:tokens", usage.total_tokens)
                sync_redis.incrbyfloat(f"budget:pipeline:{usage.pipeline_stage}:cost", usage.cost_usd)
            
            self._update_budget_cache_sync(usage.provider, sync_redis)
            
            sync_redis.close()
            print(f"[BUDGET] Recorded ${usage.cost_usd:.6f} for {usage.model_id} (provider: {usage.provider})")
        except Exception as e:
            print(f"[BUDGET ERROR] Failed to record usage sync: {e}")
    
    async def _update_redis(self, usage: UsageRecord):
        try:
            pipe = self.redis_client.pipeline()
            
            pipe.incrbyfloat(f"budget:provider:{usage.provider}:spent", usage.cost_usd)
            pipe.incrbyfloat(f"budget:model:{usage.provider}:{usage.model_id}:spent", usage.cost_usd)
            pipe.incrby(f"budget:model:{usage.provider}:{usage.model_id}:tokens", usage.total_tokens)
            pipe.incrby(f"budget:model:{usage.provider}:{usage.model_id}:prompt_tokens", usage.prompt_tokens)
            pipe.incrby(f"budget:model:{usage.provider}:{usage.model_id}:completion_tokens", usage.completion_tokens)
            
            if usage.pipeline_stage:
                pipe.incrby(f"budget:pipeline:{usage.pipeline_stage}:tokens", usage.total_tokens)
                pipe.incrbyfloat(f"budget:pipeline:{usage.pipeline_stage}:cost", usage.cost_usd)
            
            pipe.incrby(f"budget:task:{usage.task_id}:tokens", usage.total_tokens)
            pipe.incrbyfloat(f"budget:task:{usage.task_id}:cost", usage.cost_usd)
            pipe.expire(f"budget:task:{usage.task_id}:tokens", 86400)
            pipe.expire(f"budget:task:{usage.task_id}:cost", 86400)
            
            await pipe.execute()
            
            await self._update_budget_cache(usage.provider)
        except Exception as e:
            logger.error(f"Failed to update Redis: {e}")
    
    async def _save_to_postgres(self, usage: UsageRecord):
        if not self.db_pool:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO task_usage 
                    (task_id, workflow_id, step_id, pipeline_stage, provider, model_id,
                     prompt_tokens, completion_tokens, total_tokens, cost_usd, task_type, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    usage.task_id,
                    usage.workflow_id,
                    usage.step_id,
                    usage.pipeline_stage,
                    usage.provider,
                    usage.model_id,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                    usage.cost_usd,
                    usage.task_type,
                    usage.metadata
                )
                
                await conn.execute(
                    """
                    INSERT INTO usage_daily_summary 
                    (summary_date, provider, model_id, pipeline_stage, total_tasks, total_tokens,
                     prompt_tokens, completion_tokens, total_cost_usd)
                    VALUES (CURRENT_DATE, $1, $2, $3, 1, $4, $5, $6, $7)
                    ON CONFLICT (summary_date, provider, model_id, pipeline_stage)
                    DO UPDATE SET
                        total_tasks = usage_daily_summary.total_tasks + 1,
                        total_tokens = usage_daily_summary.total_tokens + $4,
                        prompt_tokens = usage_daily_summary.prompt_tokens + $5,
                        completion_tokens = usage_daily_summary.completion_tokens + $6,
                        total_cost_usd = usage_daily_summary.total_cost_usd + $7,
                        avg_tokens_per_task = usage_daily_summary.total_tokens / usage_daily_summary.total_tasks,
                        avg_cost_per_task = usage_daily_summary.total_cost_usd / usage_daily_summary.total_tasks
                    """,
                    usage.provider,
                    usage.model_id,
                    usage.pipeline_stage,
                    usage.total_tokens,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.cost_usd
                )
                
                if usage.pipeline_stage:
                    await conn.execute(
                        """
                        INSERT INTO pipeline_stage_stats (pipeline_stage, avg_tokens_per_occurrence,
                            avg_cost_per_occurrence, frequency_per_task, total_occurrences)
                        VALUES ($1, $2, $3, 1, 1)
                        ON CONFLICT (pipeline_stage)
                        DO UPDATE SET
                            total_occurrences = pipeline_stage_stats.total_occurrences + 1,
                            avg_tokens_per_occurrence = 
                                (pipeline_stage_stats.avg_tokens_per_occurrence * 
                                 (pipeline_stage_stats.total_occurrences - 1) + $2) / 
                                 pipeline_stage_stats.total_occurrences,
                            avg_cost_per_occurrence = 
                                (pipeline_stage_stats.avg_cost_per_occurrence * 
                                 (pipeline_stage_stats.total_occurrences - 1) + $3) / 
                                 pipeline_stage_stats.total_occurrences,
                            last_updated = NOW()
                        """,
                        usage.pipeline_stage,
                        usage.total_tokens,
                        usage.cost_usd
                    )
        except Exception as e:
            logger.error(f"Failed to save to Postgres: {e}")
    
    async def _update_budget_cache(self, provider: str = "openrouter"):
        """Update the cached budget summary for sync retrieval."""
        if not self.redis_client:
            return
        
        try:
            spent = float(await self.redis_client.get(f"budget:provider:{provider}:spent") or 0)
            limit = float(await self.redis_client.get(f"budget:provider:{provider}:limit") or 0)
            
            if limit <= 0:
                return
            
            remaining = limit - spent
            pct = (spent / limit) * 100
            
            status = "✅" if pct < 80 else "⚠️" if pct < 100 else "🔴"
            
            BudgetTracker._last_budget_summary = f"{status} Budget: ${spent:.4f} spent | ${remaining:.2f} remaining ({pct:.1f}% used)"
            
            await self.redis_client.set("budget:last_summary", BudgetTracker._last_budget_summary, ex=3600)
        except Exception as e:
            logger.error(f"Failed to update budget cache: {e}")
    
    def _update_budget_cache_sync(self, provider: str = "openrouter", sync_redis=None):
        """Update the cached budget summary synchronously."""
        try:
            if not sync_redis:
                return
            
            spent = float(sync_redis.get(f"budget:provider:{provider}:spent") or 0)
            limit = float(sync_redis.get(f"budget:provider:{provider}:limit") or 0)
            
            if limit <= 0:
                limit = 20.0
                sync_redis.set(f"budget:provider:{provider}:limit", limit)
            
            remaining = limit - spent
            pct = (spent / limit) * 100
            
            status = "✅" if pct < 80 else "⚠️" if pct < 100 else "🔴"
            
            BudgetTracker._last_budget_summary = f"{status} Budget: ${spent:.4f} spent | ${remaining:.2f} remaining ({pct:.1f}% used)"
            sync_redis.set("budget:last_summary", BudgetTracker._last_budget_summary, ex=3600)
        except Exception as e:
            logger.error(f"Failed to update budget cache sync: {e}")
    
    async def _check_thresholds(self, usage: UsageRecord) -> BudgetCheck:
        provider_spent = 0.0
        provider_limit = 0.0
        provider_threshold = 0.80
        model_spent = 0.0
        model_limit = 0.0
        
        if self.redis_client:
            try:
                provider_spent = float(await self.redis_client.get(f"budget:provider:{usage.provider}:spent") or 0)
                provider_limit = float(await self.redis_client.get(f"budget:provider:{usage.provider}:limit") or 0)
                provider_threshold = float(await self.redis_client.get(f"budget:provider:{usage.provider}:threshold") or 0.80)
                
                model_spent = float(await self.redis_client.get(f"budget:model:{usage.provider}:{usage.model_id}:spent") or 0)
                model_limit = float(await self.redis_client.get(f"budget:model:{usage.provider}:{usage.model_id}:limit") or provider_limit)
                
                tasks_since_alert = int(await self.redis_client.get(f"budget:provider:{usage.provider}:tasks_since_alert") or 0)
                alert_interval = int(await self.redis_client.get(f"budget:provider:{usage.provider}:alert_interval") or 5)
            except Exception as e:
                logger.error(f"Failed to get budget from Redis: {e}")
        
        if self.db_pool and provider_limit == 0:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT budget_limit_usd, threshold_pct, alert_interval_tasks FROM provider_budgets WHERE provider = $1",
                        usage.provider
                    )
                    if row:
                        provider_limit = float(row["budget_limit_usd"])
                        provider_threshold = float(row["threshold_pct"])
                        alert_interval = row["alert_interval_tasks"]
            except Exception as e:
                logger.error(f"Failed to get budget from DB: {e}")
        
        provider_pct = provider_spent / provider_limit if provider_limit > 0 else 0
        model_pct = model_spent / model_limit if model_limit > 0 else 0
        
        should_alert = False
        alert_type = None
        
        if provider_limit > 0 and provider_pct >= provider_threshold:
            if tasks_since_alert >= alert_interval:
                should_alert = True
                alert_type = "provider_threshold"
        
        if model_limit > 0 and model_pct >= provider_threshold:
            if tasks_since_alert >= alert_interval:
                should_alert = True
                alert_type = alert_type or "model_threshold"
        
        if should_alert and self.redis_client:
            await self.redis_client.set(f"budget:provider:{usage.provider}:tasks_since_alert", 0)
            await self.redis_client.set(f"budget:provider:{usage.provider}:alert_sent", datetime.utcnow().isoformat())
        elif self.redis_client:
            await self.redis_client.incr(f"budget:provider:{usage.provider}:tasks_since_alert")
        
        return BudgetCheck(
            provider=usage.provider,
            provider_spent=provider_spent,
            provider_limit=provider_limit,
            provider_pct=provider_pct,
            model_id=usage.model_id,
            model_spent=model_spent,
            model_limit=model_limit,
            model_pct=model_pct,
            should_alert=should_alert,
            alert_type=alert_type
        )
    
    async def get_status(self, provider: str = None, model_id: str = None) -> Dict[str, Any]:
        result = {}
        
        if not self.redis_client:
            return {"error": "Redis not initialized"}
        
        providers = [provider] if provider else ["openrouter", "google", "anthropic"]
        
        for prov in providers:
            try:
                spent = float(await self.redis_client.get(f"budget:provider:{prov}:spent") or 0)
                limit = float(await self.redis_client.get(f"budget:provider:{prov}:limit") or 0)
                threshold = float(await self.redis_client.get(f"budget:provider:{prov}:threshold") or 0.80)
                
                result[prov] = {
                    "spent": spent,
                    "limit": limit,
                    "remaining": limit - spent if limit > 0 else None,
                    "threshold": threshold,
                    "pct_used": spent / limit if limit > 0 else 0,
                    "status": "ok" if (limit == 0 or spent / limit < threshold) else "warning"
                }
                
                if model_id:
                    model_spent = float(await self.redis_client.get(f"budget:model:{prov}:{model_id}:spent") or 0)
                    model_tokens = int(await self.redis_client.get(f"budget:model:{prov}:{model_id}:tokens") or 0)
                    result[prov]["model"] = {
                        "model_id": model_id,
                        "spent": model_spent,
                        "tokens": model_tokens
                    }
            except Exception as e:
                result[prov] = {"error": str(e)}
        
        return result
    
    async def set_provider_budget(
        self, 
        provider: str, 
        limit: float, 
        threshold: float = 0.80,
        alert_interval: int = 5
    ) -> bool:
        if self.redis_client:
            await self.redis_client.set(f"budget:provider:{provider}:limit", str(limit))
            await self.redis_client.set(f"budget:provider:{provider}:threshold", str(threshold))
            await self.redis_client.set(f"budget:provider:{provider}:alert_interval", str(alert_interval))
        
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO provider_budgets (provider, budget_limit_usd, threshold_pct, alert_interval_tasks)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (provider)
                        DO UPDATE SET
                            budget_limit_usd = $2,
                            threshold_pct = $3,
                            alert_interval_tasks = $4,
                            updated_at = NOW()
                        """,
                        provider, limit, threshold, alert_interval
                    )
                return True
            except Exception as e:
                logger.error(f"Failed to set provider budget in DB: {e}")
                return False
        
        return True
    
    async def get_pipeline_stats(self, days: int = 7) -> list:
        if not self.db_pool:
            return []
        
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT 
                        pipeline_stage,
                        SUM(total_tasks) as total_tasks,
                        SUM(total_tokens) as total_tokens,
                        SUM(total_cost_usd) as total_cost,
                        SUM(total_tokens)::float / NULLIF(SUM(total_tasks), 0) as avg_tokens,
                        SUM(total_cost_usd)::float / NULLIF(SUM(total_tasks), 0) as avg_cost
                    FROM usage_daily_summary
                    WHERE summary_date >= CURRENT_DATE - INTERVAL '%s days'
                    AND pipeline_stage IS NOT NULL
                    GROUP BY pipeline_stage
                    ORDER BY total_cost DESC
                    """,
                    days
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pipeline stats: {e}")
            return []
    
    async def get_budget_summary(self, provider: str = "openrouter") -> str:
        """Get a concise budget summary string for injection into responses."""
        if not self.redis_client:
            return ""
        
        try:
            spent = float(await self.redis_client.get(f"budget:provider:{provider}:spent") or 0)
            limit = float(await self.redis_client.get(f"budget:provider:{provider}:limit") or 0)
            
            if limit <= 0:
                return ""
            
            remaining = limit - spent
            pct = (spent / limit) * 100
            
            status = "✅" if pct < 80 else "⚠️" if pct < 100 else "🔴"
            
            summary = f"{status} Budget: ${spent:.4f} spent | ${remaining:.2f} remaining ({pct:.1f}% used)"
            
            await self.redis_client.set("budget:last_summary", summary, ex=3600)
            
            return summary
        except Exception as e:
            logger.error(f"Failed to get budget summary: {e}")
            return ""
    
    def get_budget_summary_sync(self, provider: str = "openrouter") -> str:
        """Synchronous method to get last cached budget summary."""
        if not self.redis_client:
            return self._last_budget_summary or ""
        
        try:
            import redis
            sync_redis = redis.Redis.from_url(self.redis_client.connection_pool.connection_kwargs.get('url', 'redis://redis:6379'))
            summary = sync_redis.get("budget:last_summary")
            if summary:
                return summary.decode('utf-8')
        except Exception:
            pass
        
        return self._last_budget_summary or ""
    
    _last_budget_summary: str = ""


budget_tracker = BudgetTracker()
