"""
Scheduled Tasks API

REST API endpoints for managing scheduled tasks.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.control.scheduler.models import (
    CronPreview,
    ScheduledTaskCreate,
    ScheduledTaskResponse,
    ScheduledTaskSummary,
    ScheduledTaskUpdate,
    ScheduledTaskList,
    TaskHistoryList,
    TaskHistoryResponse,
    ScheduleStats,
)
from src.control.scheduler.parser import (
    get_human_description,
    get_next_runs,
    validate_cron,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


async def get_db_pool():
    """Get database pool."""
    import os
    import yaml
    
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        try:
            with open("config/bootstrap.yaml") as f:
                bootstrap = yaml.safe_load(f)
            database_url = bootstrap.get("database_url", "")
        except Exception:
            pass
    
    if not database_url:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    return await asyncpg.create_pool(database_url, min_size=1, max_size=5)


@router.get("", response_model=ScheduledTaskList)
async def list_schedules(
    enabled: Optional[bool] = None,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """List all scheduled tasks with optional filtering."""
    offset = (page - 1) * page_size
    
    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1
        
        if enabled is not None:
            conditions.append(f"enabled = ${param_idx}")
            params.append(enabled)
            param_idx += 1
        
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        
        if task_type:
            conditions.append(f"task_type = ${param_idx}")
            params.append(task_type)
            param_idx += 1
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        count_query = f"SELECT COUNT(*) FROM scheduled_tasks {where_clause}"
        total = await conn.fetchval(count_query, *params)
        
        query = f"""
            SELECT id, uuid, name, description, schedule_type, task_type,
                   enabled, status, next_run_at, last_run_at, last_run_status, run_count
            FROM scheduled_tasks
            {where_clause}
            ORDER BY next_run_at ASC NULLS LAST, name ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([page_size, offset])
        
        rows = await conn.fetch(query, *params)
        items = [ScheduledTaskSummary(**dict(row)) for row in rows]
        
        return ScheduledTaskList(
            items=items, total=total, page=page, page_size=page_size,
            has_more=(offset + len(items)) < total
        )


@router.post("", response_model=ScheduledTaskResponse, status_code=201)
async def create_schedule(
    task: ScheduledTaskCreate,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Create a new scheduled task."""
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM scheduled_tasks WHERE name = $1", task.name
        )
        if existing:
            raise HTTPException(status_code=400, detail="Task with this name already exists")
        
        row = await conn.fetchrow(
            """
            INSERT INTO scheduled_tasks (
                name, description, schedule_type, cron_expression,
                interval_seconds, scheduled_for, timezone,
                task_type, task_payload, enabled, timeout_seconds,
                max_failures, max_runs, notify_on_success, notify_on_failure,
                notify_on_start, notification_channel, notification_recipients,
                tags, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14, $15, $16, $17, $18::jsonb, $19::jsonb, $20)
            RETURNING *
            """,
            task.name, task.description, task.schedule_type.value,
            task.cron_expression, task.interval_seconds, task.scheduled_for,
            task.timezone, task.task_type.value, json.dumps(task.task_payload),
            task.enabled, task.timeout_seconds, task.max_failures, task.max_runs,
            task.notify_on_success, task.notify_on_failure, task.notify_on_start,
            task.notification_channel.value, json.dumps(task.notification_recipients),
            json.dumps(task.tags), task.created_by
        )
        
        return ScheduledTaskResponse(**dict(row))


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
async def get_schedule(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Get a specific scheduled task by ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM scheduled_tasks WHERE id = $1", task_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        return ScheduledTaskResponse(**dict(row))


@router.put("/{task_id}", response_model=ScheduledTaskResponse)
async def update_schedule(
    task_id: int,
    update: ScheduledTaskUpdate,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Update a scheduled task."""
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM scheduled_tasks WHERE id = $1", task_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        
        updates = ["updated_at = NOW()"]
        params = [task_id]
        param_idx = 2
        
        update_data = update.model_dump(exclude_unset=True)
        
        for field, value in update_data.items():
            if value is not None:
                if hasattr(value, 'value'):
                    updates.append(f"{field} = ${param_idx}")
                    params.append(value.value)
                else:
                    updates.append(f"{field} = ${param_idx}")
                    params.append(value)
                param_idx += 1
        
        if len(updates) == 1:
            return ScheduledTaskResponse(**dict(existing))
        
        query = f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE id = $1 RETURNING *"
        row = await conn.fetchrow(query, *params)
        return ScheduledTaskResponse(**dict(row))


@router.delete("/{task_id}")
async def delete_schedule(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Delete a scheduled task."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM scheduled_tasks WHERE id = $1", task_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        return {"status": "deleted", "id": task_id}


@router.post("/{task_id}/enable")
async def enable_schedule(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Enable a scheduled task."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE scheduled_tasks SET enabled = true, status = 'idle', updated_at = NOW() WHERE id = $1",
            task_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        return {"status": "enabled", "id": task_id}


@router.post("/{task_id}/disable")
async def disable_schedule(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Disable a scheduled task."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE scheduled_tasks SET enabled = false, status = 'disabled', updated_at = NOW() WHERE id = $1",
            task_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        return {"status": "disabled", "id": task_id}


@router.post("/{task_id}/run")
async def run_schedule_now(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Trigger immediate execution of a scheduled task."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM scheduled_tasks WHERE id = $1", task_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        
        await conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = NOW() WHERE id = $1", task_id
        )
        return {"status": "triggered", "id": task_id, "message": "Task will execute on next daemon cycle"}


@router.get("/{task_id}/history", response_model=TaskHistoryList)
async def get_schedule_history(
    task_id: int,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Get execution history for a scheduled task."""
    offset = (page - 1) * page_size
    
    async with pool.acquire() as conn:
        task = await conn.fetchrow(
            "SELECT id, name FROM scheduled_tasks WHERE id = $1", task_id
        )
        if not task:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        
        conditions = ["scheduled_task_id = $1"]
        params = [task_id]
        param_idx = 2
        
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        
        where_clause = f"WHERE {' AND '.join(conditions)}"
        
        count_query = f"SELECT COUNT(*) FROM scheduled_task_history {where_clause}"
        total = await conn.fetchval(count_query, *params)
        
        query = f"""
            SELECT h.* FROM scheduled_task_history h
            {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([page_size, offset])
        
        rows = await conn.fetch(query, *params)
        items = []
        for row in rows:
            item_dict = dict(row)
            item_dict['task_name'] = task['name']
            items.append(TaskHistoryResponse(**item_dict))
        
        return TaskHistoryList(
            items=items, total=total, page=page, page_size=page_size,
            has_more=(offset + len(items)) < total
        )


@router.get("/{task_id}/stats", response_model=ScheduleStats)
async def get_schedule_stats(task_id: int, pool: asyncpg.Pool = Depends(get_db_pool)):
    """Get execution statistics for a scheduled task."""
    async with pool.acquire() as conn:
        task = await conn.fetchrow(
            "SELECT id, name FROM scheduled_tasks WHERE id = $1", task_id
        )
        if not task:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        
        stats = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) as total_runs,
                COUNT(*) FILTER (WHERE status = 'success') as successful_runs,
                COUNT(*) FILTER (WHERE status = 'failed') as failed_runs,
                COALESCE(AVG(duration_seconds), 0) as avg_duration,
                COALESCE(SUM(cost_usd), 0) as total_cost,
                MAX(started_at) FILTER (WHERE status = 'success') as last_success_at,
                MAX(started_at) FILTER (WHERE status = 'failed') as last_failure_at
            FROM scheduled_task_history
            WHERE scheduled_task_id = $1
            """,
            task_id
        )
        
        total = stats['total_runs'] or 0
        successful = stats['successful_runs'] or 0
        
        return ScheduleStats(
            task_id=task_id, task_name=task['name'],
            total_runs=total, successful_runs=successful,
            failed_runs=stats['failed_runs'] or 0,
            success_rate=(successful / total * 100) if total > 0 else 0.0,
            average_duration_seconds=float(stats['avg_duration'] or 0),
            total_cost_usd=float(stats['total_cost'] or 0),
            last_success_at=stats['last_success_at'],
            last_failure_at=stats['last_failure_at']
        )


@router.post("/preview-cron", response_model=CronPreview)
async def preview_cron_expression(
    expression: str = Query(..., description="Cron expression"),
    timezone: str = Query("UTC", description="Timezone"),
    count: int = Query(5, ge=1, le=20, description="Number of runs")
):
    """Preview upcoming runs for a cron expression."""
    if not validate_cron(expression):
        raise HTTPException(status_code=400, detail="Invalid cron expression")
    
    next_runs = get_next_runs(expression, count, timezone)
    description = get_human_description(expression)
    
    return CronPreview(
        expression=expression, next_runs=next_runs, description=description
    )


@router.get("/daemon/status")
async def get_daemon_status():
    """Get scheduler daemon status."""
    import subprocess
    
    result = subprocess.run(
        ["pgrep", "-f", "start_scheduler.py"],
        capture_output=True,
        text=True
    )
    
    pids = result.stdout.strip().split('\n') if result.stdout.strip() else []
    is_running = len(pids) > 0 and pids[0] != ''
    
    status = {
        "running": is_running,
        "pid": int(pids[0]) if is_running else None,
        "pids": [int(p) for p in pids if p] if is_running else [],
        "uptime": None,
        "last_log": None
    }
    
    if is_running:
        try:
            import os
            stat = os.popen(f"ps -p {pids[0]} -o etime=").read().strip()  # nosec B605 - pid is an integer from psutil, not user input
            status["uptime"] = stat
        except:
            pass
    
    try:
        with open("/tmp/scheduler.log", "r") as f:  # nosec B108 - read-only log file, known fixed path
            lines = f.readlines()[-20:]
            status["last_log"] = "".join(lines)
    except:
        status["last_log"] = "No log file found"
    
    return status


@router.get("/history/recent", response_model=TaskHistoryList)
async def get_recent_history(
    limit: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Get recent execution history across all tasks."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT h.*, t.name as task_name
            FROM scheduled_task_history h
            JOIN scheduled_tasks t ON h.scheduled_task_id = t.id
            ORDER BY h.started_at DESC
            LIMIT $1
            """,
            limit
        )
        
        items = [TaskHistoryResponse(**dict(row)) for row in rows]
        return TaskHistoryList(
            items=items, total=len(items), page=1, page_size=limit, has_more=False
        )
