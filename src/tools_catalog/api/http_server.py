import asyncio
import json
import os
import uuid
from typing import Callable, Any, Optional

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from src.plugins.base import Tool, Envelope, ToolContext
from src.web.admin import create_admin_router

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


class HttpServerTool(Tool):
    type = "api"
    name = "http_server"
    description = "Local HTTP+SSE server for TUIs, scripts, and curl"
    listen = True
    node = "genesis"

    def initialize(self, config: dict) -> None:
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 8000)
        self.api_key = config.get("api_key", "")
        self.redis_url = config.get("redis_url", "redis://localhost:6379")
        self.app = None
        self._on_message = None
        self._redis = None

    def get_tool_schemas(self) -> list[dict]:
        return []

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        pass

    async def start_listener(self, on_message: Callable[[Envelope], Any]) -> None:
        self._on_message = on_message
        
        if aioredis:
            try:
                self._redis = aioredis.from_url(self.redis_url)
            except Exception:
                self._redis = None
        
        self.app = FastAPI(title="AI Orchestrator")
        
        admin_router = create_admin_router()
        self.app.include_router(admin_router)
        
        self._setup_task_routes()
        
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        asyncio.create_task(server.serve())

    def _setup_task_routes(self):
        @self.app.post("/task")
        async def submit_task(request: Request):
            body = await request.json()
            envelope = self._body_to_envelope(body)
            task_id = envelope.id
            if self._on_message:
                asyncio.create_task(self._on_message(envelope))
            return {"task_id": task_id}

        @self.app.post("/task/run")
        async def run_task(request: Request):
            body = await request.json()
            envelope = self._body_to_envelope(body)
            task_id = envelope.id
            if self._on_message:
                asyncio.create_task(self._on_message(envelope))
            result = await self._wait_for_result(task_id)
            return result

        @self.app.get("/task/{task_id}/stream")
        async def stream_task(task_id: str):
            return EventSourceResponse(self._sse_generator(task_id))

        @self.app.get("/task/{task_id}/files/{filename}")
        async def download_file(task_id: str, filename: str):
            workspace = os.path.join("/tmp", "tasks", task_id)  # nosec B108 - ephemeral task workspace under /tmp
            filepath = os.path.join(workspace, filename)
            if not os.path.exists(filepath):
                raise HTTPException(status_code=404, detail="File not found")
            from fastapi.responses import FileResponse
            return FileResponse(filepath)

    def _body_to_envelope(self, body: dict) -> Envelope:
        return Envelope(
            id=body.get("task_id", str(uuid.uuid4())),
            source=body.get("source", "http"),
            task_description=body.get("description", ""),
            payload=body.get("payload"),
            content_type=body.get("content_type", "text/plain"),
            reply_to=body.get("source", "http"),
            metadata=body.get("context", {}),
            tool_scope=body.get("tool_scope"),
        )

    async def _wait_for_result(self, task_id: str) -> dict:
        if not self._redis:
            return {"error": "Redis not available"}
        
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(f"task:{task_id}:events")
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                event = json.loads(msg["data"])
                if event.get("event") in ("done", "error"):
                    return event.get("data", {})
        finally:
            await pubsub.unsubscribe(f"task:{task_id}:events")
        return {"error": "Timeout"}

    async def _sse_generator(self, task_id: str):
        if not self._redis:
            yield {"event": "error", "data": json.dumps({"error": "Redis not available"})}
            return
        
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(f"task:{task_id}:events")
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                event = json.loads(msg["data"])
                yield {
                    "event": event.get("event", "progress"),
                    "data": json.dumps(event.get("data", {}))
                }
                if event.get("event") in ("done", "error"):
                    break
        finally:
            await pubsub.unsubscribe(f"task:{task_id}:events")

    async def stop_listener(self) -> None:
        if self._redis:
            await self._redis.close()


tool_class = HttpServerTool