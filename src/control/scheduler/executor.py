"""
Task Executor

Executes scheduled tasks via Temporal and manages execution history.
"""

import json
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

from src.control.scheduler.models import (
    ExecutionStatus,
    ScheduledTaskInDB,
    TaskHistoryCreate,
    TaskType,
)

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes scheduled tasks and records history."""
    
    def __init__(self, db_pool=None, scheduler=None):
        """
        Initialize executor.
        
        Args:
            db_pool: Database connection pool
            scheduler: TaskScheduler instance for Temporal submission
        """
        self.db_pool = db_pool
        self.scheduler = scheduler
    
    async def execute_task(self, task: ScheduledTaskInDB) -> Tuple[str, Dict[str, Any]]:
        """
        Execute a scheduled task.
        
        Args:
            task: ScheduledTaskInDB instance
            
        Returns:
            Tuple of (temporal_task_id, result_dict)
        """
        task_id = None
        result = {
            "status": ExecutionStatus.RUNNING,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "temporal_task_id": None,
            "error": None
        }
        
        try:
            # Submit task to Temporal based on task type
            if task.task_type == TaskType.AGENT:
                task_id, execution_result = await self._execute_agent_task(task)
            elif task.task_type == TaskType.SHELL:
                task_id, execution_result = await self._execute_shell_task(task)
            elif task.task_type == TaskType.TOOL:
                task_id, execution_result = await self._execute_tool_task(task)
            elif task.task_type == TaskType.WORKFLOW:
                task_id, execution_result = await self._execute_workflow_task(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            result["temporal_task_id"] = task_id
            result["status"] = ExecutionStatus.SUCCESS
            result["result"] = execution_result
            
        except Exception as e:
            logger.error(f"Task execution failed for {task.name}: {e}")
            result["status"] = ExecutionStatus.FAILED
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
        
        return task_id, result
    
    async def _execute_agent_task(self, task: ScheduledTaskInDB) -> Tuple[str, Dict]:
        """Execute an agent task via Temporal."""
        from src.genesis.orchestrator.scheduler import TaskScheduler
        from src.genesis.analyzer.task_analyzer import TaskAnalyzer, TaskRequirement
        
        payload = task.task_payload
        description = payload.get("description", "")
        
        # Create scheduler and analyzer
        if not self.scheduler:
            self.scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
        
        analyzer = TaskAnalyzer(config_path="config/profiles.yaml")
        
        # Analyze task requirements
        task_req = TaskRequirement(
            estimated_duration_seconds=payload.get("timeout_seconds", task.timeout_seconds),
            memory_mb=512,
            reasoning_complexity="medium",
            context_length=2000,
            specialization=payload.get("specialization", "general")
        )
        analysis = analyzer.analyze(task_req)
        
        # Build agent payload
        agent_payload = json.dumps({
            "task_type": "agent",
            "description": description,
            "repo_url": payload.get("repo_url", ""),
            "max_tool_calls": payload.get("max_tool_calls", 20),
            "max_cost_usd": payload.get("max_cost_usd", 0.50),
            "specialization": payload.get("specialization", "general")
        })
        
        # Submit to Temporal
        temporal_task_id = await self.scheduler.submit_task(
            agent_payload,
            analysis.model_dump(),
            source=f"scheduled:{task.id}"
        )
        
        # Wait for completion with timeout
        final_status = await self.scheduler.wait_for_completion(
            temporal_task_id,
            timeout=task.timeout_seconds
        )
        
        # Get result
        detail = await self.scheduler.get_task_detail(temporal_task_id)
        result = detail.get("result", {})
        
        if final_status == "COMPLETED":
            return temporal_task_id, {
                "status": "success",
                "summary": result.get("summary", ""),
                "tool_call_count": result.get("tool_call_count", 0),
                "cost_usd": result.get("total_cost_usd", 0),
                "duration_seconds": result.get("duration_seconds", 0)
            }
        else:
            return temporal_task_id, {
                "status": "failed",
                "error": result.get("summary", f"Task {final_status}")
            }
    
    async def _execute_shell_task(self, task: ScheduledTaskInDB) -> Tuple[str, Dict]:
        """Execute a shell command task."""
        import subprocess
        
        payload = task.task_payload
        command = payload.get("command", "")
        
        if not command:
            raise ValueError("Shell task missing 'command' in payload")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds
            )
            
            output = result.stdout or result.stderr
            success = result.returncode == 0
            
            return None, {
                "status": "success" if success else "failed",
                "output": output[:5000],  # Truncate
                "return_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Shell command timed out after {task.timeout_seconds}s")
    
    async def _execute_tool_task(self, task: ScheduledTaskInDB) -> Tuple[str, Dict]:
        """Execute a tool task directly."""
        from src.plugins.loader import load_tools_sync
        from src.plugins.registry import registry
        
        payload = task.task_payload
        tool_name = payload.get("tool_name")
        function_name = payload.get("function_name")
        arguments = payload.get("arguments", {})
        
        if not tool_name or not function_name:
            raise ValueError("Tool task missing 'tool_name' or 'function_name'")
        
        # Ensure tools are loaded
        if not registry._tools:
            await load_tools_sync(node="worker")
        
        # Get tool instance
        tool = registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}. Available: {list(registry._tools.keys())}")
        
        # Build namespaced function name
        namespaced_fn = f"{tool_name}__{function_name}"
        
        if namespaced_fn not in registry._fn_lookup:
            raise ValueError(f"Function not found: {namespaced_fn}. Available: {list(registry._fn_lookup.keys())[:10]}...")
        
        # Execute tool
        from src.plugins.base import ToolContext
        ctx = ToolContext(workspace_dir="/tmp", task_id="", envelope=None)
        
        result = await tool.call_tool(function_name, arguments, ctx)
        
        return None, {
            "status": "success",
            "result": result[:5000] if isinstance(result, str) else result
        }
    
    async def _execute_workflow_task(self, task: ScheduledTaskInDB) -> Tuple[str, Dict]:
        """Execute a Temporal workflow task."""
        payload = task.task_payload
        workflow_name = payload.get("workflow_name")
        workflow_args = payload.get("args", {})
        
        if not workflow_name:
            raise ValueError("Workflow task missing 'workflow_name'")
        
        # This would integrate with Temporal workflow submission
        # For now, raise NotImplementedError
        raise NotImplementedError("Workflow tasks not yet implemented")
    
    async def record_history(
        self,
        task_id: int,
        temporal_task_id: Optional[str],
        status: ExecutionStatus,
        result_summary: Optional[str] = None,
        error_message: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        cost_usd: Optional[float] = None,
        tool_call_count: Optional[int] = None,
        full_result: Optional[Dict] = None
    ) -> int:
        """
        Record execution history in database.
        
        Args:
            task_id: Scheduled task ID
            temporal_task_id: Temporal task ID
            status: Execution status
            result_summary: Brief result summary
            error_message: Error message if failed
            duration_seconds: Execution duration
            cost_usd: Cost in USD
            tool_call_count: Number of tool calls
            full_result: Full result dict
            
        Returns:
            History record ID
        """
        if not self.db_pool:
            logger.warning("No database pool, skipping history record")
            return 0
        
        async with self.db_pool.acquire() as conn:
            started_at = datetime.now(timezone.utc) - timedelta(seconds=duration_seconds) if duration_seconds else datetime.now(timezone.utc)
            record_id = await conn.fetchval(
                """
                INSERT INTO scheduled_task_history 
                (scheduled_task_id, started_at, completed_at, duration_seconds,
                 temporal_task_id, status, result_summary, error_message,
                 cost_usd, tool_call_count, full_result)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                task_id,
                started_at,
                datetime.now(timezone.utc),
                duration_seconds,
                temporal_task_id,
                status.value,
                result_summary,
                error_message,
                cost_usd,
                tool_call_count,
                json.dumps(full_result) if full_result else None
            )
        
        return record_id
    
    async def update_task_state(
        self,
        task_id: int,
        status: str = None,
        last_run_status: str = None,
        last_run_task_id: str = None,
        last_run_duration_seconds: int = None,
        last_error: str = None,
        increment_run: bool = False,
        increment_failure: bool = False
    ):
        """
        Update scheduled task state after execution.
        
        Args:
            task_id: Scheduled task ID
            status: New status
            last_run_status: Last run status
            last_run_task_id: Last Temporal task ID
            last_run_duration_seconds: Last run duration
            last_error: Last error message
            increment_run: Whether to increment run_count
            increment_failure: Whether to increment failure counters
        """
        if not self.db_pool:
            return
        
        async with self.db_pool.acquire() as conn:
            updates = ["last_run_at = NOW()", "updated_at = NOW()"]
            params = [task_id]
            param_idx = 2
            
            if status:
                updates.append(f"status = ${param_idx}")
                params.append(status)
                param_idx += 1
            
            if last_run_status:
                updates.append(f"last_run_status = ${param_idx}")
                params.append(last_run_status)
                param_idx += 1
            
            if last_run_task_id:
                updates.append(f"last_run_task_id = ${param_idx}")
                params.append(last_run_task_id)
                param_idx += 1
            
            if last_run_duration_seconds is not None:
                updates.append(f"last_run_duration_seconds = ${param_idx}")
                params.append(last_run_duration_seconds)
                param_idx += 1
            
            if last_error:
                updates.append(f"last_error = ${param_idx}")
                params.append(last_error)
                param_idx += 1
            
            if increment_run:
                updates.append("run_count = run_count + 1")
            
            if increment_failure:
                updates.extend([
                    "failure_count = failure_count + 1",
                    "consecutive_failures = consecutive_failures + 1"
                ])
            else:
                updates.append("consecutive_failures = 0")
            
            query = f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE id = $1"
            await conn.execute(query, *params)
