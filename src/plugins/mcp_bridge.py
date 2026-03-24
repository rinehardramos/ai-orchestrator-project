import asyncio
import json
from typing import Any, Dict, Optional
from src.plugins.base import Tool, ToolContext


class MCPBridgeTool(Tool):
    type = "mcp"
    name = "mcp_bridge"
    description = "Wraps an external MCP (Model Context Protocol) server as a tool"
    node = "worker"

    def initialize(self, config: dict) -> None:
        self.config = config
        self.transport = config.get("transport", "stdio")
        self.command = config.get("command", "")
        self.url = config.get("url", "")
        self._process = None
        self._tools_cache = None
        self._request_id = 0
        self._initialized = False

    def get_tool_schemas(self) -> list[dict]:
        if self._tools_cache is None:
            loop = asyncio.new_event_loop()
            try:
                self._tools_cache = loop.run_until_complete(self._fetch_tools())
            finally:
                loop.close()
        return self._tools_cache or []

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> str:
        await self._ensure_connected()
        
        response = await self._send_jsonrpc("tools/call", {
            "name": tool_name,
            "arguments": args
        })
        
        if "error" in response:
            return f"MCP Error: {response['error'].get('message', str(response['error']))}"
        
        result = response.get("result", {})
        content = result.get("content", [])
        
        texts = []
        for c in content:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
        
        if texts:
            return "\n".join(texts)
        
        return json.dumps(result, indent=2)

    async def _fetch_tools(self) -> list[dict]:
        await self._ensure_connected()
        
        response = await self._send_jsonrpc("tools/list", {})
        mcp_tools = response.get("result", {}).get("tools", [])
        
        schemas = []
        for t in mcp_tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.get("name", "unknown"),
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                }
            })
        
        return schemas

    async def _ensure_connected(self):
        if self._initialized:
            return
        
        if self.transport == "stdio" and self._process is None:
            self._process = await asyncio.create_subprocess_exec(
                *self.command.split(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            await self._send_jsonrpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-orchestrator", "version": "1.0"}
            })
            
            await self._send_jsonrpc("notifications/initialized", {})
            self._initialized = True

    async def _send_jsonrpc(self, method: str, params: dict) -> dict:
        if self.transport == "stdio":
            if self._process is None:
                raise RuntimeError("MCP process not started")
            
            self._request_id += 1
            
            is_notification = method.startswith("notifications/")
            msg_id = None if is_notification else self._request_id
            
            msg = json.dumps({
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": method,
                "params": params
            })
            
            self._process.stdin.write((msg + "\n").encode())
            await self._process.stdin.drain()
            
            if is_notification:
                return {}
            
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=30.0
            )
            
            return json.loads(line.decode().strip())
        
        elif self.transport == "http":
            import httpx
            async with httpx.AsyncClient() as client:
                self._request_id += 1
                response = await client.post(
                    self.url,
                    json={
                        "jsonrpc": "2.0",
                        "id": self._request_id,
                        "method": method,
                        "params": params
                    },
                    timeout=30.0
                )
                return response.json()
        
        raise ValueError(f"Unknown transport: {self.transport}")

    async def stop_listener(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
            self._initialized = False


tool_class = MCPBridgeTool
