import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from src.plugins.base import Tool, ToolContext


class SchedulerTool(Tool):
    type = "scheduler"
    name = "scheduler"
    description = "Create, update, list, and delete scheduled tasks"
    node = "worker"
    
    _method_map = {
        "schedule_create": "_create",
        "schedule_update": "_update",
        "schedule_delete": "_delete",
        "schedule_list": "_list",
        "schedule_get": "_get",
        "schedule_enable": "_enable",
        "schedule_disable": "_disable",
        "schedule_run_now": "_run_now",
    }

    def initialize(self, config: dict) -> None:
        self.config = config
        self.db_url = config.get("database_url", "")

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "schedule_create",
                    "description": "Create a new scheduled task. Can be one-time, recurring (interval), or cron-based.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Unique name for the scheduled task"
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The prompt/instruction for the AI to execute when triggered"
                            },
                            "schedule_type": {
                                "type": "string",
                                "enum": ["once", "interval", "cron"],
                                "description": "Type of schedule: 'once' for one-time, 'interval' for recurring, 'cron' for cron expression"
                            },
                            "scheduled_for": {
                                "type": "string",
                                "description": "ISO datetime for when to run (for 'once' type). E.g., '2024-01-15T09:00:00Z'"
                            },
                            "interval_seconds": {
                                "type": "integer",
                                "description": "Interval in seconds between runs (for 'interval' type). E.g., 3600 for hourly"
                            },
                            "cron_expression": {
                                "type": "string",
                                "description": "Cron expression (for 'cron' type). E.g., '0 9 * * *' for daily at 9am"
                            },
                            "timezone": {
                                "type": "string",
                                "description": "Timezone for schedule (default: Asia/Manila)",
                                "default": "Asia/Manila"
                            },
                            "max_runs": {
                                "type": "integer",
                                "description": "Maximum number of times to run (optional, default: unlimited)"
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "description": "Task timeout in seconds (default: 300)",
                                "default": 300
                            }
                        },
                        "required": ["name", "prompt", "schedule_type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_update",
                    "description": "Update an existing scheduled task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to update"
                            },
                            "prompt": {
                                "type": "string",
                                "description": "New prompt/instruction"
                            },
                            "enabled": {
                                "type": "boolean",
                                "description": "Enable or disable the task"
                            },
                            "cron_expression": {
                                "type": "string",
                                "description": "New cron expression"
                            },
                            "interval_seconds": {
                                "type": "integer",
                                "description": "New interval in seconds"
                            },
                            "scheduled_for": {
                                "type": "string",
                                "description": "New scheduled datetime for one-time tasks"
                            },
                            "max_runs": {
                                "type": "integer",
                                "description": "New max runs limit"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_delete",
                    "description": "Delete a scheduled task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to delete"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_list",
                    "description": "List all scheduled tasks",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "enabled_only": {
                                "type": "boolean",
                                "description": "Only list enabled tasks (default: false)"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_get",
                    "description": "Get details of a specific scheduled task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to get"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_enable",
                    "description": "Enable a scheduled task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to enable"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_disable",
                    "description": "Disable a scheduled task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to disable"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_run_now",
                    "description": "Trigger a scheduled task to run immediately",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the task to run now"
                            }
                        },
                        "required": ["name"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        method = self._method_map.get(tool_name)
        if not method:
            return f"Unknown function: {tool_name}"
        
        handler = getattr(self, method, None)
        if not handler:
            return f"Method not implemented: {tool_name}"
        
        return await handler(args, ctx)

    async def _get_db_conn(self):
        import asyncpg
        import os
        
        db_url = self.db_url or os.environ.get("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL not configured")
        
        return await asyncpg.connect(db_url)

    async def _create(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        prompt = args.get("prompt")
        schedule_type = args.get("schedule_type")
        timezone_str = args.get("timezone", "Asia/Manila")
        timeout_seconds = args.get("timeout_seconds", 300)
        max_runs = args.get("max_runs")
        
        if not name or not prompt or not schedule_type:
            return "Error: name, prompt, and schedule_type are required"
        
        task_payload = {"description": prompt, "specialization": "general"}
        
        conn = await self._get_db_conn()
        try:
            existing = await conn.fetchval(
                "SELECT id FROM scheduled_tasks WHERE name = $1", name
            )
            if existing:
                return f"Error: Task '{name}' already exists"
            
            insert_sql = """
                INSERT INTO scheduled_tasks (
                    name, description, schedule_type, cron_expression,
                    interval_seconds, scheduled_for, timezone,
                    task_type, task_payload, enabled, timeout_seconds,
                    max_runs, notify_on_failure, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, 'idle')
                RETURNING id, uuid
            """
            
            params = [
                name,
                prompt[:200],
                schedule_type,
                args.get("cron_expression"),
                args.get("interval_seconds"),
                args.get("scheduled_for"),
                timezone_str,
                "agent",
                json.dumps(task_payload),
                True,
                timeout_seconds,
                max_runs,
                True
            ]
            
            row = await conn.fetchrow(insert_sql, *params)
            
            return {
                "status": "created",
                "id": row["id"],
                "uuid": str(row["uuid"]),
                "name": name,
                "schedule_type": schedule_type,
                "message": f"Scheduled task '{name}' created successfully"
            }
        finally:
            await conn.close()

    async def _update(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            existing = await conn.fetchrow(
                "SELECT id FROM scheduled_tasks WHERE name = $1", name
            )
            if not existing:
                return f"Error: Task '{name}' not found"
            
            updates = []
            params = []
            param_idx = 1
            
            if "prompt" in args:
                updates.append(f"description = ${param_idx}")
                params.append(args["prompt"][:200])
                param_idx += 1
                updates.append(f"task_payload = ${param_idx}::jsonb")
                params.append(json.dumps({"description": args["prompt"], "specialization": "general"}))
                param_idx += 1
            
            if "enabled" in args:
                updates.append(f"enabled = ${param_idx}")
                params.append(args["enabled"])
                param_idx += 1
            
            if "cron_expression" in args:
                updates.append(f"cron_expression = ${param_idx}")
                params.append(args["cron_expression"])
                param_idx += 1
            
            if "interval_seconds" in args:
                updates.append(f"interval_seconds = ${param_idx}")
                params.append(args["interval_seconds"])
                param_idx += 1
            
            if "scheduled_for" in args:
                updates.append(f"scheduled_for = ${param_idx}")
                params.append(args["scheduled_for"])
                param_idx += 1
            
            if "max_runs" in args:
                updates.append(f"max_runs = ${param_idx}")
                params.append(args["max_runs"])
                param_idx += 1
            
            if not updates:
                return "No fields to update"
            
            updates.append("updated_at = NOW()")
            params.append(name)
            
            sql = f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE name = ${param_idx}"
            await conn.execute(sql, *params)
            
            return {"status": "updated", "name": name, "message": f"Task '{name}' updated successfully"}
        finally:
            await conn.close()

    async def _delete(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            result = await conn.execute(
                "DELETE FROM scheduled_tasks WHERE name = $1 RETURNING id", name
            )
            
            if result == "DELETE 0":
                return f"Error: Task '{name}' not found"
            
            return {"status": "deleted", "name": name, "message": f"Task '{name}' deleted successfully"}
        finally:
            await conn.close()

    async def _list(self, args: dict, ctx: ToolContext) -> Any:
        enabled_only = args.get("enabled_only", False)
        
        conn = await self._get_db_conn()
        try:
            if enabled_only:
                rows = await conn.fetch(
                    "SELECT id, name, description, schedule_type, enabled, status, next_run_at, run_count FROM scheduled_tasks WHERE enabled = true ORDER BY next_run_at"
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, name, description, schedule_type, enabled, status, next_run_at, run_count FROM scheduled_tasks ORDER BY next_run_at"
                )
            
            tasks = []
            for row in rows:
                tasks.append({
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "schedule_type": row["schedule_type"],
                    "enabled": row["enabled"],
                    "status": row["status"],
                    "next_run_at": str(row["next_run_at"]) if row["next_run_at"] else None,
                    "run_count": row["run_count"]
                })
            
            return {"total": len(tasks), "tasks": tasks}
        finally:
            await conn.close()

    async def _get(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            row = await conn.fetchrow(
                "SELECT * FROM scheduled_tasks WHERE name = $1", name
            )
            
            if not row:
                return f"Error: Task '{name}' not found"
            
            task = dict(row)
            if task.get("task_payload"):
                task["task_payload"] = task["task_payload"]
            if task.get("uuid"):
                task["uuid"] = str(task["uuid"])
            for key, val in task.items():
                if isinstance(val, datetime):
                    task[key] = str(val)
            
            return task
        finally:
            await conn.close()

    async def _enable(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            result = await conn.execute(
                "UPDATE scheduled_tasks SET enabled = true, status = 'idle', consecutive_failures = 0, updated_at = NOW() WHERE name = $1",
                name
            )
            
            if result == "UPDATE 0":
                return f"Error: Task '{name}' not found"
            
            return {"status": "enabled", "name": name, "message": f"Task '{name}' enabled"}
        finally:
            await conn.close()

    async def _disable(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            result = await conn.execute(
                "UPDATE scheduled_tasks SET enabled = false, status = 'disabled', updated_at = NOW() WHERE name = $1",
                name
            )
            
            if result == "UPDATE 0":
                return f"Error: Task '{name}' not found"
            
            return {"status": "disabled", "name": name, "message": f"Task '{name}' disabled"}
        finally:
            await conn.close()

    async def _run_now(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        if not name:
            return "Error: name is required"
        
        conn = await self._get_db_conn()
        try:
            result = await conn.fetchrow(
                "UPDATE scheduled_tasks SET next_run_at = NOW(), updated_at = NOW() WHERE name = $1 RETURNING id",
                name
            )
            
            if not result:
                return f"Error: Task '{name}' not found"
            
            return {
                "status": "triggered",
                "name": name,
                "message": f"Task '{name}' triggered to run immediately. Check status in a few moments."
            }
        finally:
            await conn.close()


tool_class = SchedulerTool
