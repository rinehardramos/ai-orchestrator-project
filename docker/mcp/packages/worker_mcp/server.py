"""stdio MCP server for the generic worker API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_URL = "http://host.docker.internal:8100"


class WorkerApiError(RuntimeError):
    pass


class WorkerApiClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        self.base_url = (base_url or os.environ.get("CONTROL_URL") or DEFAULT_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("CONTROL_API_KEY") or ""
        self.timeout = timeout
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["X-Control-API-Key"] = self.api_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(
                method,
                url,
                json=json_body,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise WorkerApiError(f"{method} {url} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise WorkerApiError(
                f"{method} {path} returned {resp.status_code}: {resp.text[:500]}"
            )
        if not resp.content:
            return None
        return resp.json()

    # ── Tool implementations ────────────────────────────────────────
    def list_workers(self) -> Any:
        return self._request("GET", "/workers")

    def upsert_worker(
        self,
        name: str,
        model: str,
        provider: str,
        allowed_tools: list[str],
    ) -> Any:
        return self._request(
            "POST",
            "/workers",
            json_body={
                "name": name,
                "model": model,
                "provider": provider,
                "allowed_tools": allowed_tools,
            },
        )

    def delete_worker(self, name: str) -> Any:
        return self._request("DELETE", f"/workers/{name}")

    def dispatch_task(
        self,
        specialization: str,
        task_description: str,
        max_tool_calls: int = 50,
        max_cost_usd: float = 0.50,
    ) -> Any:
        return self._request(
            "POST",
            "/tasks",
            json_body={
                "specialization": specialization,
                "task_description": task_description,
                "max_tool_calls": max_tool_calls,
                "max_cost_usd": max_cost_usd,
            },
        )

    def get_task_status(self, task_id: str) -> Any:
        return self._request("GET", f"/tasks/{task_id}")

    def healthz(self) -> Any:
        return self._request("GET", "/healthz")


def run() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    client = WorkerApiClient()
    server: Any = Server("worker-mcp")

    tools = [
        Tool(
            name="healthz",
            description="Liveness probe for the worker-api service (no auth required).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_workers",
            description="List every specialization (worker) registered in the control plane.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="upsert_worker",
            description=(
                "Create or replace a worker specialization. Same name = upsert. "
                "allowed_tools is the per-specialization tool scope the execution "
                "worker will honor."
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
            name="delete_worker",
            description="Delete a worker specialization by name.",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="dispatch_task",
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
            description="Look up a task by id. Reports submission metadata from the offline queue db.",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
    ]

    dispatch = {
        "healthz": client.healthz,
        "list_workers": client.list_workers,
        "upsert_worker": client.upsert_worker,
        "delete_worker": client.delete_worker,
        "dispatch_task": client.dispatch_task,
        "get_task_status": client.get_task_status,
    }

    @server.list_tools()
    async def _list():  # type: ignore[no-untyped-def]
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict):  # type: ignore[no-untyped-def]
        arguments = arguments or {}
        fn = dispatch.get(name)
        if fn is None:
            return [TextContent(type="text", text=f"error: unknown tool {name!r}")]
        try:
            result = fn(**arguments)
        except Exception as exc:
            return [TextContent(type="text", text=f"error: {exc}")]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())
