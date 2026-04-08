"""stdio MCP server exposing worker CRUD + dispatch + status.

Wraps :class:`WorkersHandlers` in the ``mcp`` SDK's stdio transport.
The handlers module is transport-free, so it can be imported and
exercised directly without spawning this server.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.execution.workers_mcp.handlers import WorkersHandlers

logger = logging.getLogger(__name__)


def run_stdio_server() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "The 'mcp' package is required to run the workers MCP server. "
            "Install with: pip install mcp"
        ) from exc

    handlers = WorkersHandlers()
    server: Any = Server("workers")

    tools = [
        Tool(
            name="list_workers",
            description="List all specializations (workers) from the shared config DB namespace.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="create_worker",
            description=(
                "Create or replace a specialization in the shared config DB "
                "namespace. Same name = upsert."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "model": {"type": "string"},
                    "provider": {"type": "string"},
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "model", "provider", "allowed_tools"],
            },
        ),
        Tool(
            name="dispatch_worker",
            description=(
                "Submit an agent task routed to a named specialization. "
                "Returns the Temporal task_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "specialization": {"type": "string"},
                    "task_description": {"type": "string"},
                    "max_tool_calls": {"type": "integer", "default": 50},
                    "max_cost_usd": {"type": "number", "default": 0.50},
                },
                "required": ["specialization", "task_description"],
            },
        ),
        Tool(
            name="get_task_status",
            description=(
                "Look up a task in the local offline_queue.db by task_id. "
                "Reports submission metadata; for live workflow status query "
                "Temporal directly."
            ),
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="run_assistant",
            description=(
                "Sugar: load an Obsidian note (default 'AGENT INSTRUCTIONS.md') "
                "from the synced vault collection and dispatch it to the "
                "'assistant' specialization."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note": {"type": "string", "default": "AGENT INSTRUCTIONS.md"}
                },
            },
        ),
    ]

    @server.list_tools()
    async def _list_tools():  # type: ignore[no-untyped-def]
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):  # type: ignore[no-untyped-def]
        arguments = arguments or {}
        try:
            if name == "list_workers":
                result = handlers.list_workers()
            elif name == "create_worker":
                result = handlers.create_worker(**arguments)
            elif name == "dispatch_worker":
                result = await handlers.dispatch_worker(**arguments)
            elif name == "get_task_status":
                result = handlers.get_task_status(**arguments)
            elif name == "run_assistant":
                result = await handlers.run_assistant(**arguments)
            else:
                raise ValueError(f"unknown tool {name!r}")
        except Exception as exc:
            return [TextContent(type="text", text=f"error: {exc}")]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    run_stdio_server()
