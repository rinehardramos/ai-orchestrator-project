"""
YAML Schedule Loader

Loads scheduled tasks from YAML configuration file.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import asyncpg
import yaml

from src.genesis.scheduler.models import (
    NotificationChannel,
    ScheduleType,
    TaskType,
)
from src.genesis.scheduler.parser import validate_cron

logger = logging.getLogger(__name__)


async def load_schedules_from_yaml(
    yaml_path: str = "config/schedules.yaml",
    database_url: Optional[str] = None,
    sync: bool = True
) -> Dict[str, str]:
    """
    Load scheduled tasks from YAML file into database.
    
    Args:
        yaml_path: Path to YAML file
        database_url: Database connection string
        sync: Whether to update existing tasks
        
    Returns:
        Dict with 'created', 'updated', 'skipped' counts
    """
    if not os.path.exists(yaml_path):
        logger.info(f"No schedules file at {yaml_path}")
        return {"created": 0, "updated": 0, "skipped": 0, "error": "File not found"}
    
    with open(yaml_path) as f:
        config = yaml.safe_load(f)
    
    if not config or 'schedules' not in config:
        logger.info("No schedules defined in YAML")
        return {"created": 0, "updated": 0, "skipped": 0}
    
    if not database_url:
        database_url = _get_database_url()
    
    if not database_url:
        return {"created": 0, "updated": 0, "skipped": 0, "error": "No database URL"}
    
    results = {"created": 0, "updated": 0, "skipped": 0}
    
    if sync:
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    else:
        pool = database_url
    
    try:
        async with pool.acquire() if isinstance(pool, asyncpg.Pool) else pool as conn:
            for name, schedule in config['schedules'].items():
                try:
                    result = await _upsert_schedule(conn, name, schedule, sync)
                    results[result] += 1
                except Exception as e:
                    logger.error(f"Failed to load schedule '{name}': {e}")
                    results['skipped'] += 1
    finally:
        if isinstance(pool, asyncpg.Pool):
            await pool.close()
    
    logger.info(f"YAML schedules loaded: {results}")
    return results


async def _upsert_schedule(
    conn,
    name: str,
    schedule: dict,
    update_existing: bool = True
) -> str:
    """
    Insert or update a schedule in the database.
    
    Returns: 'created', 'updated', or 'skipped'
    """
    if not schedule.get('enabled', True):
        return 'skipped'
    
    schedule_type = schedule.get('schedule_type', 'cron')
    task_type = schedule.get('task_type', 'agent')
    
    cron_expr = schedule.get('cron_expression')
    interval_seconds = schedule.get('interval_seconds')
    scheduled_for = schedule.get('scheduled_for')
    
    if schedule_type == 'cron':
        if not cron_expr:
            raise ValueError(f"Cron schedule '{name}' missing cron_expression")
        if not validate_cron(cron_expr):
            raise ValueError(f"Invalid cron expression for '{name}': {cron_expr}")
    elif schedule_type == 'interval':
        if not interval_seconds:
            raise ValueError(f"Interval schedule '{name}' missing interval_seconds")
    elif schedule_type == 'once':
        if not scheduled_for:
            raise ValueError(f"One-time schedule '{name}' missing scheduled_for")
    
    task_payload = schedule.get('task_payload', {})
    if task_type == 'agent' and 'description' in schedule:
        task_payload['description'] = schedule['description']
    if task_type == 'shell' and 'command' in schedule:
        task_payload['command'] = schedule['command']
    
    existing = await conn.fetchrow(
        "SELECT id FROM scheduled_tasks WHERE name = $1", name
    )
    
    if existing:
        if not update_existing:
            return 'skipped'
        
        await conn.execute(
            """
            UPDATE scheduled_tasks SET
                description = $2,
                schedule_type = $3,
                cron_expression = $4,
                interval_seconds = $5,
                scheduled_for = $6,
                timezone = $7,
                task_type = $8,
                task_payload = $9,
                timeout_seconds = $10,
                max_failures = $11,
                max_runs = $12,
                notify_on_success = $13,
                notify_on_failure = $14,
                notify_on_start = $15,
                notification_channel = $16,
                tags = $17,
                updated_at = NOW()
            WHERE name = $1
            """,
            name,
            schedule.get('description'),
            schedule_type,
            cron_expr,
            interval_seconds,
            scheduled_for,
            schedule.get('timezone', 'UTC'),
            task_type,
            task_payload,
            schedule.get('timeout_seconds', 300),
            schedule.get('max_failures', 3),
            schedule.get('max_runs'),
            schedule.get('notify_on_success', False),
            schedule.get('notify_on_failure', True),
            schedule.get('notify_on_start', False),
            schedule.get('notification_channel', 'telegram'),
            schedule.get('tags', [])
        )
        return 'updated'
    
    else:
        await conn.execute(
            """
            INSERT INTO scheduled_tasks (
                name, description, schedule_type, cron_expression,
                interval_seconds, scheduled_for, timezone,
                task_type, task_payload, enabled, timeout_seconds,
                max_failures, max_runs, notify_on_success, notify_on_failure,
                notify_on_start, notification_channel, tags, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            """,
            name,
            schedule.get('description'),
            schedule_type,
            cron_expr,
            interval_seconds,
            scheduled_for,
            schedule.get('timezone', 'UTC'),
            task_type,
            task_payload,
            schedule.get('enabled', True),
            schedule.get('timeout_seconds', 300),
            schedule.get('max_failures', 3),
            schedule.get('max_runs'),
            schedule.get('notify_on_success', False),
            schedule.get('notify_on_failure', True),
            schedule.get('notify_on_start', False),
            schedule.get('notification_channel', 'telegram'),
            schedule.get('tags', []),
            'yaml_loader'
        )
        return 'created'


def _get_database_url() -> Optional[str]:
    """Get database URL from environment or bootstrap.yaml."""
    database_url = os.environ.get("DATABASE_URL")
    
    if not database_url:
        try:
            with open("config/bootstrap.yaml") as f:
                bootstrap = yaml.safe_load(f)
            database_url = bootstrap.get("database_url", "")
        except Exception:
            pass
    
    return database_url


def create_sample_yaml(output_path: str = "config/schedules.yaml"):
    """Create a sample schedules.yaml file."""
    sample = {
        'schedules': {
            'daily_email_summary': {
                'description': 'Summarize unread emails from the last 24 hours',
                'schedule_type': 'cron',
                'cron_expression': '0 9 * * *',
                'timezone': 'UTC',
                'task_type': 'agent',
                'description': 'Check gmail inbox and summarize unread emails from the last 24 hours',
                'task_payload': {
                    'description': 'Check gmail_blackopstech047 inbox and summarize unread emails',
                    'specialization': 'general',
                    'max_tool_calls': 10
                },
                'timeout_seconds': 300,
                'max_failures': 3,
                'notify_on_success': False,
                'notify_on_failure': True,
                'tags': ['email', 'daily']
            },
            'hourly_health_check': {
                'description': 'Check system health every hour',
                'schedule_type': 'interval',
                'interval_seconds': 3600,
                'task_type': 'shell',
                'task_payload': {
                    'command': 'curl -s http://localhost:8080/health | jq .'
                },
                'notify_on_failure': True,
                'tags': ['health', 'monitoring']
            },
            'weekly_drive_report': {
                'description': 'Generate weekly report of Drive files',
                'schedule_type': 'cron',
                'cron_expression': '0 17 * * 5',
                'timezone': 'America/New_York',
                'task_type': 'agent',
                'task_payload': {
                    'description': 'Search gdrive_blackopstech047 for files modified this week and create a summary report',
                    'specialization': 'general'
                },
                'notify_on_success': True,
                'tags': ['reports', 'weekly']
            }
        }
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w') as f:
        yaml.dump(sample, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Created sample schedules at {output_path}")
    return output_path
