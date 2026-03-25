"""
Scheduler Daemon

Background process that checks for due scheduled tasks and executes them.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import yaml

from src.control.scheduler.executor import TaskExecutor
from src.control.scheduler.models import ExecutionStatus, ScheduledTaskInDB
from src.control.scheduler.parser import calculate_next_run_at, get_next_run

logger = logging.getLogger(__name__)


class SchedulerDaemon:
    """
    Background daemon that executes scheduled tasks.
    
    Polls the database for due tasks and executes them via Temporal.
    """
    
    def __init__(
        self,
        database_url: str,
        poll_interval: int = 60,
        timezone: str = "UTC"
    ):
        """
        Initialize scheduler daemon.
        
        Args:
            database_url: Database connection string
            poll_interval: Seconds between polls (default: 60)
            timezone: Default timezone for schedule evaluation
        """
        self.database_url = database_url
        self.poll_interval = poll_interval
        self.timezone = timezone
        self.db_pool: Optional[asyncpg.Pool] = None
        self.executor: Optional[TaskExecutor] = None
        self.running = False
        self._shutdown_event = asyncio.Event()
    
    async def start(self):
        """Start the scheduler daemon."""
        logger.info("Starting Scheduler Daemon...")
        
        # Initialize database pool
        self.db_pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10
        )
        
        # Initialize executor
        self.executor = TaskExecutor(db_pool=self.db_pool)
        
        self.running = True
        
        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        
        logger.info(f"Scheduler Daemon started (poll interval: {self.poll_interval}s)")
        
        # Main loop
        while self.running:
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error(f"Error in scheduler cycle: {e}")
            
            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.poll_interval
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass
    
    async def stop(self):
        """Stop the scheduler daemon gracefully."""
        logger.info("Stopping Scheduler Daemon...")
        self.running = False
        self._shutdown_event.set()
        
        if self.db_pool:
            await self.db_pool.close()
        
        logger.info("Scheduler Daemon stopped")
    
    async def _run_cycle(self):
        """Run one scheduler cycle."""
        now = datetime.now(timezone.utc)
        logger.debug(f"Running scheduler cycle at {now.isoformat()}")
        
        # Get due tasks
        due_tasks = await self._get_due_tasks()
        
        if due_tasks:
            logger.info(f"Found {len(due_tasks)} task(s) due for execution")
        
        # Execute each due task
        for task_data in due_tasks:
            try:
                task = ScheduledTaskInDB(**dict(task_data))
                await self._execute_task(task)
            except Exception as e:
                logger.error(f"Failed to execute task {task_data.get('name')}: {e}")
        
        # Update next_run_at for cron tasks
        await self._update_cron_schedules()
        
        # Check for tasks that exceeded max failures
        await self._disable_failed_tasks()
    
    async def _get_due_tasks(self) -> list:
        """Get tasks that are due for execution."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM scheduled_tasks
                WHERE enabled = true
                  AND status IN ('idle', 'running')
                  AND next_run_at <= NOW()
                  AND (max_runs IS NULL OR run_count < max_runs)
                ORDER BY next_run_at ASC
                """
            )
        return rows
    
    async def _execute_task(self, task: ScheduledTaskInDB):
        """
        Execute a single scheduled task.
        
        Args:
            task: Task to execute
        """
        logger.info(f"Executing task: {task.name} (ID: {task.id})")
        
        # Mark as running
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_tasks SET status = 'running' WHERE id = $1",
                task.id
            )
        
        start_time = datetime.now(timezone.utc)
        status = ExecutionStatus.SUCCESS
        error_message = None
        result_summary = None
        cost_usd = None
        tool_call_count = None
        full_result = None
        
        try:
            # Execute task
            temporal_task_id, result = await self.executor.execute_task(task)
            
            status_str = result.get("status", "success")
            if status_str == "success" or status_str == ExecutionStatus.SUCCESS:
                status = ExecutionStatus.SUCCESS
            elif status_str == "failed" or status_str == ExecutionStatus.FAILED:
                status = ExecutionStatus.FAILED
                error_message = result.get("error", "Unknown error")
            
            # Get result summary - handle different types
            raw_result = result.get("summary") or result.get("result") or result.get("output") or ""
            if isinstance(raw_result, dict):
                result_summary = str(raw_result)[:1000]
            elif isinstance(raw_result, str):
                result_summary = raw_result[:1000]
            else:
                result_summary = str(raw_result)[:1000]
            
            cost_usd = result.get("cost_usd")
            tool_call_count = result.get("tool_call_count")
            full_result = result
            
        except Exception as e:
            logger.error(f"Task {task.name} failed with exception: {e}")
            status = ExecutionStatus.FAILED
            error_message = str(e)
            temporal_task_id = None
        
        end_time = datetime.now(timezone.utc)
        duration_seconds = int((end_time - start_time).total_seconds())
        
        # Record history
        await self.executor.record_history(
            task_id=task.id,
            temporal_task_id=temporal_task_id,
            status=status,
            result_summary=result_summary,
            error_message=error_message,
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            tool_call_count=tool_call_count,
            full_result=full_result
        )
        
        # Update task state
        await self.executor.update_task_state(
            task_id=task.id,
            status="idle",
            last_run_status=status.value,
            last_run_task_id=temporal_task_id,
            last_run_duration_seconds=duration_seconds,
            last_error=error_message,
            increment_run=True,
            increment_failure=(status == ExecutionStatus.FAILED)
        )
        
        # Send notification if configured
        if task.notify_on_failure and status == ExecutionStatus.FAILED:
            await self._send_notification(task, status, error_message)
        elif task.notify_on_success and status == ExecutionStatus.SUCCESS:
            await self._send_notification(task, status, result_summary)
        
        logger.info(f"Task {task.name} completed with status: {status.value}")
    
    async def _update_cron_schedules(self):
        """Update next_run_at for cron-based tasks."""
        async with self.db_pool.acquire() as conn:
            # Get cron tasks that need next_run_at update
            rows = await conn.fetch(
                """
                SELECT id, cron_expression, timezone, last_run_at
                FROM scheduled_tasks
                WHERE enabled = true
                  AND schedule_type = 'cron'
                  AND cron_expression IS NOT NULL
                  AND (next_run_at IS NULL OR next_run_at <= NOW())
                """
            )
            
            for row in rows:
                try:
                    next_run = get_next_run(
                        row['cron_expression'],
                        row['timezone'] or 'UTC',
                        row['last_run_at'] or datetime.now(timezone.utc)
                    )
                    
                    if next_run:
                        await conn.execute(
                            "UPDATE scheduled_tasks SET next_run_at = $1 WHERE id = $2",
                            next_run,
                            row['id']
                        )
                except Exception as e:
                    logger.error(f"Failed to update next_run_at for task {row['id']}: {e}")
    
    async def _disable_failed_tasks(self):
        """Disable tasks that exceeded max consecutive failures."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE scheduled_tasks
                SET enabled = false, status = 'disabled'
                WHERE enabled = true
                  AND consecutive_failures >= max_failures
                  AND max_failures > 0
                RETURNING id, name
                """
            )
            
            if result:
                logger.warning(f"Disabled task(s) due to consecutive failures")
    
    async def _send_notification(self, task: ScheduledTaskInDB, status: ExecutionStatus, message: str):
        """Send notification about task execution."""
        try:
            from src.genesis.notifier import TelegramNotifier
            
            notifier = TelegramNotifier()
            
            status_emoji = "✅" if status == ExecutionStatus.SUCCESS else "❌"
            text = (
                f"{status_emoji} *Scheduled Task: {task.name}*\n\n"
                f"Status: {status.value}\n"
                f"Time: {datetime.now(timezone.utc).isoformat()}\n"
            )
            
            if message:
                text += f"\n{message[:500]}"
            
            await notifier.send_message(text)
            
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")


async def main():
    """Main entry point for scheduler daemon."""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Load configuration
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        # Try to load from bootstrap.yaml
        try:
            with open("config/bootstrap.yaml") as f:
                bootstrap = yaml.safe_load(f)
            database_url = bootstrap.get("database_url", "")
        except Exception:
            pass
    
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    # Start daemon
    daemon = SchedulerDaemon(database_url=database_url)
    
    try:
        await daemon.start()
    except KeyboardInterrupt:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
