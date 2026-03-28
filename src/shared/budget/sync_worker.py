import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class BudgetSyncWorker:
    def __init__(self, redis_client=None, db_pool=None, interval_seconds: int = 60):
        self.redis_client = redis_client
        self.db_pool = db_pool
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"Budget sync worker started (interval: {self.interval_seconds}s)")
    
    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Budget sync worker stopped")
    
    async def _sync_loop(self):
        while self._running:
            try:
                await self._sync_redis_to_postgres()
                await self._aggregate_daily_summaries()
            except Exception as e:
                logger.error(f"Sync error: {e}")
            
            await asyncio.sleep(self.interval_seconds)
    
    async def _sync_redis_to_postgres(self):
        if not self.redis_client or not self.db_pool:
            return
        
        try:
            providers = ["openrouter", "google", "anthropic"]
            
            for provider in providers:
                spent = await self.redis_client.get(f"budget:provider:{provider}:spent")
                limit = await self.redis_client.get(f"budget:provider:{provider}:limit")
                
                if spent and limit:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE provider_budgets
                            SET current_balance_usd = $1 - $2,
                                updated_at = NOW()
                            WHERE provider = $1
                            """,
                            float(limit), float(spent), provider
                        )
            
            logger.debug("Synced Redis budget state to Postgres")
        except Exception as e:
            logger.error(f"Failed to sync Redis to Postgres: {e}")
    
    async def _aggregate_daily_summaries(self):
        if not self.db_pool:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO task_patterns (task_type, avg_steps, avg_total_tokens, avg_cost_usd, sample_count)
                    SELECT 
                        task_type,
                        AVG(step_count)::int as avg_steps,
                        AVG(total_tokens)::bigint as avg_total_tokens,
                        AVG(cost_usd) as avg_cost_usd,
                        COUNT(*) as sample_count
                    FROM (
                        SELECT 
                            task_type,
                            task_id,
                            COUNT(DISTINCT step_id) as step_count,
                            SUM(total_tokens) as total_tokens,
                            SUM(cost_usd) as cost_usd
                        FROM task_usage
                        WHERE created_at >= NOW() - INTERVAL '1 day'
                        GROUP BY task_type, task_id
                    ) sub
                    GROUP BY task_type
                    ON CONFLICT (task_type, task_complexity)
                    DO UPDATE SET
                        avg_steps = EXCLUDED.avg_steps,
                        avg_total_tokens = EXCLUDED.avg_total_tokens,
                        avg_cost_usd = EXCLUDED.avg_cost_usd,
                        sample_count = EXCLUDED.sample_count,
                        last_updated = NOW()
                    """
                )
            
            logger.debug("Aggregated daily summaries")
        except Exception as e:
            logger.error(f"Failed to aggregate daily summaries: {e}")
    
    async def sync_provider_balance_from_api(self, provider: str):
        if provider == "openrouter":
            from .provider_apis import OpenRouterClient
            client = OpenRouterClient()
            if self.redis_client:
                await client.sync_balance_to_redis(self.redis_client)
