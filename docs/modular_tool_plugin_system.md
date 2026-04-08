# Modular Tool Plugin System

## What This Is

A plugin system where every capability (Telegram, email, shell, webhook, database, etc.) is
a **Tool** — a Python class that exposes atomic functions to the agent. Tools are stored in a
database, can be enabled/disabled at runtime, and support multiple instances with different
credentials (e.g. two Gmail accounts, three MySQL servers).

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│ Genesis Node                                                      │
│                                                                    │
│  bootstrap.yaml ──► Loader ──► ToolRegistry                       │
│       │                            │                               │
│       ▼                            ▼                               │
│  Postgres DB          ┌─── Listener tools (start_listener)        │
│  (tool configs,       │    • telegram (polls bot API)              │
│   credentials)        │    • http_server (binds :8000)             │
│       │               │                                            │
│       ▼               │    These feed tasks into the scheduler.    │
│  Redis Cache          │    Workers never touch these.              │
│  (TTL 60s)            └────────────────────────────────────────── │
└──────────────────────────────────────────────────────────────────┘
                        │ Temporal
┌──────────────────────────────────────────────────────────────────┐
│ Worker Node                                                       │
│                                                                    │
│  bootstrap.yaml ──► Loader ──► ToolRegistry                       │
│                                    │                               │
│                         ┌─── Action tools (get_tool_schemas)       │
│                         │    • shell_exec, read_file, write_file   │
│                         │    • email_send, email_read_inbox        │
│                         │    • chat_send, http_request             │
│                         │    • Any MCP server tools                │
│                         │                                          │
│                         │    Agent sees these as callable functions.│
│                         │    Worker routes calls via registry.      │
│                         └──────────────────────────────────────── │
└──────────────────────────────────────────────────────────────────┘
```

## Two Surfaces Per Tool

Every tool has up to two surfaces. They never cross.

| Surface | Who calls it | Purpose |
|---------|-------------|---------|
| `start_listener()` | Genesis node at startup | Always-on ingestion. Feeds tasks into scheduler. |
| `get_tool_schemas()` + `call_tool()` | Worker agent during task | Action functions the agent can call. |

Example: the Telegram tool has both surfaces.
- Genesis calls `start_listener()` → polls for incoming messages → submits tasks.
- Agent calls `chat_send(text, chat_id)` → sends a reply back to Telegram.

Example: the `http_server` tool is listener-only.
- Genesis calls `start_listener()` → binds port 8000, accepts HTTP requests.
- `get_tool_schemas()` returns `[]` — the agent never calls it.

Example: the `shell` tool is action-only.
- No listener. `listen = False`.
- Agent calls `shell_exec(command)` → runs command, returns output.

---

## Tool ABC (`src/plugins/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
import uuid, time


@dataclass
class Envelope:
    """Universal message container. Travels from source tool → scheduler → worker."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""              # tool instance name: "telegram", "sqs_orders"
    timestamp: float = field(default_factory=time.time)

    # Payload — native Python type. The bus serializes for transport.
    payload: Any = None           # str, dict, bytes — whatever the source produces
    content_type: str = "text/plain"  # MIME hint for binary payloads

    # Routing
    reply_to: str = ""            # where to send result (defaults to source)
    correlation_id: str = ""      # links result back to request

    # Agent interface
    task_description: str = ""    # what the agent should do
    metadata: dict = field(default_factory=dict)

    # Tool scoping — restricts which tool instances the agent can see.
    # None = all tools (default). List of instance names = only those tools.
    # Example: gmail_work listener sets tool_scope=["gmail_work", "shell", "filesystem"]
    # so the agent can't accidentally reply using gmail_personal.
    tool_scope: list = None


@dataclass
class ToolContext:
    """Injected by the worker into every call_tool() invocation.
    Carries per-task state the agent doesn't send."""
    workspace_dir: str = ""
    task_id: str = ""
    envelope: Envelope = field(default_factory=Envelope)


class Tool(ABC):
    """Base class for all tools. Subclass this to create a new tool."""

    # --- Class attributes set by subclass ---
    type: str = ""           # category: "chat", "email", "code", "data", "queue", etc.
    name: str = ""           # default instance name, overridden by loader from DB/config
    description: str = ""    # human-readable, shown to agent in tool list header
    listen: bool = False     # True = genesis starts this as always-on source
    node: str = "both"       # "genesis" | "worker" | "both" — where this tool loads

    def initialize(self, config: dict) -> None:
        """Called once at startup with config from DB. Store credentials here."""
        self.config = config

    @abstractmethod
    def get_tool_schemas(self) -> list[dict]:
        """Return OpenAI-compatible function schemas for agent-facing tools.
        Listener-only tools return [].
        Use GENERIC names (email_send, not gmail_work_email_send).
        Namespacing is applied automatically by the registry."""
        ...

    @abstractmethod
    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        """Execute a tool function. tool_name matches a name from get_tool_schemas().
        ctx provides workspace_dir, task_id, and the original envelope."""
        ...

    async def deliver_result(self, envelope: Envelope, result: str,
                             artifacts: list) -> None:
        """Called by scheduler after task completes to send result back to source.
        Override in tools that need custom delivery (DB update, queue ack, etc.).
        Default: no-op (chat tools override to send message)."""
        pass

    # --- Listener lifecycle (genesis-only) ---

    async def start_listener(self, on_message: Callable[[Envelope], Any]) -> None:
        """Genesis calls this at startup for tools with listen=True.
        on_message submits an Envelope to the scheduler."""
        pass

    async def stop_listener(self) -> None:
        pass
```

---

## Tool Registry (`src/plugins/registry.py`)

```python
from src.plugins.base import Tool, ToolContext
from typing import Any


class ToolNotFound(Exception):
    pass


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}       # instance_name → Tool
        self._fn_lookup: dict[str, str] = {}     # namespaced_fn → instance_name

    def register(self, tool: Tool) -> None:
        """Register a tool instance. Builds the O(1) function lookup."""
        self._tools[tool.name] = tool
        for schema in tool.get_tool_schemas():
            fn = schema["function"]["name"]
            namespaced = f"{tool.name}__{fn}"
            self._fn_lookup[namespaced] = tool.name

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_all_tool_schemas(self, specialization: str = None,
                             tool_scope: list = None) -> list[dict]:
        """Return namespaced schemas for all registered tools.
        specialization: filter to allowed function names from profiles.yaml.
        tool_scope: if set, only include these tool instance names (from Envelope).
        """
        schemas = []
        for tool in self._tools.values():
            if tool_scope is not None and tool.name not in tool_scope:
                continue
            for schema in tool.get_tool_schemas():
                fn = schema["function"]["name"]
                namespaced = dict(schema)  # shallow copy
                namespaced["function"] = dict(schema["function"])
                namespaced["function"]["name"] = f"{tool.name}__{fn}"
                namespaced["function"]["description"] = (
                    f"[{tool.name}] {schema['function']['description']}"
                )
                schemas.append(namespaced)
        if specialization:
            schemas = self._filter_by_specialization(schemas, specialization)
        return schemas

    async def call_tool(self, namespaced_name: str, args: dict,
                        ctx: ToolContext) -> Any:
        """Route a tool call. O(1) lookup via _fn_lookup dict."""
        if namespaced_name not in self._fn_lookup:
            raise ToolNotFound(f"No tool found: {namespaced_name}")
        instance_name = self._fn_lookup[namespaced_name]
        fn_name = namespaced_name.split("__", 1)[1]
        return await self._tools[instance_name].call_tool(fn_name, args, ctx)

    def get_listeners(self) -> list[Tool]:
        return [t for t in self._tools.values() if t.listen]

    def reload(self) -> None:
        """Clear and re-register all tools. Called after DB changes."""
        self._tools.clear()
        self._fn_lookup.clear()
        # Caller must re-run load_tools() after this

    def _filter_by_specialization(self, schemas, spec):
        # Load allowed_tools from profiles.yaml for this specialization
        # Filter schemas to only include allowed tool functions
        ...


# Global singleton (one per process — genesis has one, worker has one)
registry = ToolRegistry()
```

---

## Tool Loader (`src/plugins/loader.py`)

Reads tool configs from Postgres (with Redis cache). Falls back to `tools.yaml` if DB is
unavailable. Always instantiates from `tool_class` (no singletons).

```python
import importlib
import json
import logging
import os
import re
import yaml
from src.plugins.registry import registry

log = logging.getLogger(__name__)


def load_tools(bootstrap_path: str = "config/bootstrap.yaml",
               node: str = "worker") -> None:
    """Load all enabled tools from DB into the registry.
    node: 'genesis' or 'worker' — filters tools by their node field."""
    bootstrap = _load_bootstrap(bootstrap_path)
    tools = _load_tool_configs(bootstrap)

    for name, entry in tools.items():
        tool_node = entry.get("node", "both")
        if tool_node != "both" and tool_node != node:
            continue
        if not entry.get("enabled", False):
            continue
        try:
            module = importlib.import_module(entry["module"])
            tool_class = getattr(module, "tool_class")  # always use class
            instance = tool_class()
            instance.name = name  # instance name from DB key
            instance.initialize(entry.get("config", {}))
            registry.register(instance)
            log.info(f"Loaded tool: {name} ({entry['module']})")
        except Exception as e:
            log.warning(f"Failed to load tool {name}: {e}")
            # Skip this tool, continue loading others


def _load_bootstrap(path: str) -> dict:
    raw = yaml.safe_load(open(path))
    return _resolve_env_vars(raw)


def _load_tool_configs(bootstrap: dict) -> dict:
    """Try DB → Redis cache → YAML fallback."""
    try:
        return _load_from_db(bootstrap)
    except Exception as e:
        log.warning(f"DB unavailable, falling back to YAML: {e}")
        return _load_from_yaml()


def _load_from_db(bootstrap: dict) -> dict:
    # 1. Check Redis cache
    # 2. If miss, query Postgres:
    #    SELECT t.name, t.type, t.module, t.enabled, t.listen, t.node
    #    FROM tools t WHERE t.enabled = true
    # 3. For each tool, merge tool_configs + decrypted credentials
    # 4. Cache in Redis with TTL 60s
    # 5. Return dict of {name: {module, type, enabled, listen, node, config}}
    ...


def _load_from_yaml(path: str = "config/tools.yaml") -> dict:
    raw = yaml.safe_load(open(path))
    resolved = _resolve_env_vars(raw)
    return resolved.get("tools", {})


def _resolve_env_vars(obj):
    """Recursively replace ${VAR} with os.environ[VAR]."""
    if isinstance(obj, str):
        return re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj
```

---

## Config Storage

### `config/bootstrap.yaml` (checked into git, ~10 lines)

```yaml
env: production
database_url: ${DATABASE_URL}
redis_url: ${REDIS_URL}
temporal_host: ${TEMPORAL_HOST}
qdrant_url: ${QDRANT_URL}
secret_key: ${CONFIG_SECRET_KEY}
```

### Postgres Schema (`migrations/001_tools_schema.sql`)

```sql
CREATE TABLE tools (
    name        TEXT PRIMARY KEY,         -- instance name: "gmail_work", "mysql_prod"
    type        TEXT NOT NULL,            -- category: "email", "data", "chat"
    module      TEXT NOT NULL,            -- Python import path: "src.tools_catalog.email.gmail"
    enabled     BOOLEAN DEFAULT false,
    listen      BOOLEAN DEFAULT false,
    node        TEXT DEFAULT 'both',      -- "genesis" | "worker" | "both"
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tool_configs (
    tool_name   TEXT REFERENCES tools(name) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT,
    PRIMARY KEY (tool_name, key)
);

CREATE TABLE credentials (
    tool_name   TEXT REFERENCES tools(name) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       BYTEA NOT NULL,           -- AES-256-GCM encrypted
    PRIMARY KEY (tool_name, key)
);
```

### Tool Registration (3 paths, same DB tables)

**Path 1 — HTTP API:**
```bash
curl -X POST http://localhost:8000/tools/register \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "name": "gmail_work",
    "type": "email",
    "module": "src.tools_catalog.email.gmail",
    "enabled": true,
    "node": "worker",
    "config": {"imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com"},
    "credentials": {"username": "work@company.com", "password": "app-password"}
  }'
```

**Path 2 — CLI:**
```bash
python -m src.genesis.cli tools add --name gmail_work --module src.tools_catalog.email.gmail ...
```

**Path 3 — ToolBuilder (automatic):**
ToolBuilder writes the Python file and INSERTs into the tools table. See ToolBuilder section.

After any registration: invalidate Redis cache → broadcast reload to all nodes.

---

## Multi-Instance Tools

Same module, different credentials. The instance name (DB key) becomes the namespace.

```
DB rows:
  gmail_work     → module: src.tools_catalog.email.gmail, config: {username: work@...}
  gmail_personal → module: src.tools_catalog.email.gmail, config: {username: personal@...}

Loader creates two separate GmailTool instances.

Agent sees:
  gmail_work__email_send        "[gmail_work] Send an email"
  gmail_work__email_read_inbox  "[gmail_work] Read emails from inbox"
  gmail_personal__email_send        "[gmail_personal] Send an email"
  gmail_personal__email_read_inbox  "[gmail_personal] Read emails from inbox"
```

The tool module only writes generic names. Namespacing is automatic:

```python
# src/tools_catalog/email/gmail.py
class GmailTool(Tool):
    type = "email"
    name = "gmail"  # default, overridden by loader with instance name
    description = "Read and send email via IMAP/SMTP"
    node = "worker"

    def get_tool_schemas(self):
        return [
            {"type": "function", "function": {
                "name": "email_send",  # GENERIC — no prefix
                "description": "Send an email",
                "parameters": {"type": "object", "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"}
                }, "required": ["to", "subject", "body"]}
            }},
            {"type": "function", "function": {
                "name": "email_read_inbox",
                "description": "Read emails from inbox",
                "parameters": {"type": "object", "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "unread_only": {"type": "boolean", "default": True},
                    "limit": {"type": "integer", "default": 10}
                }, "required": []}
            }},
        ]

    async def call_tool(self, tool_name, args, ctx):
        if tool_name == "email_send":
            return self._send(**args)
        if tool_name == "email_read_inbox":
            return self._read_inbox(**args)

    def initialize(self, config):
        self.imap_host = config["imap_host"]
        self.smtp_host = config["smtp_host"]
        self.username = config["username"]
        self.password = config["password"]

    def _send(self, to, subject, body):
        # SMTP logic
        ...

    def _read_inbox(self, folder="INBOX", unread_only=True, limit=10):
        # IMAP logic
        ...

tool_class = GmailTool  # REQUIRED: loader instantiates from this
```

---

## File Structure (what to implement)

```
src/
  plugins/
    __init__.py
    base.py              # Tool ABC, Envelope, ToolContext (shown above)
    registry.py          # ToolRegistry with O(1) lookup (shown above)
    loader.py            # DB-backed loader with YAML fallback (shown above)
    mcp_bridge.py        # Wraps any MCP server as a Tool

  tools_catalog/
    api/
      __init__.py
      http_server.py     # listen: true, node: genesis — HTTP+SSE universal source
    chat/
      __init__.py
      telegram.py        # listen: true, node: both — wraps existing TelegramMonitor
    code/
      __init__.py
      shell.py           # shell_exec (from tools.py)
      filesystem.py      # read_file, write_file, edit_file, list_files (from tools.py)
      web.py             # web_search, fetch_url (from tools.py)
      git.py             # git_clone, git_commit, git_push (from tools.py)
    webhook/
      __init__.py
      http_client.py     # http_request (GET/POST/PUT/DELETE)
    media/
      __init__.py
      image.py           # generate_image (from tools.py, wraps Google Imagen)

  tool_builder/
    __init__.py
    builder.py           # Internal coding sub-agent
    validator.py         # Validates generated code before registration
    prompt.py            # System prompt for the coding model

config/
  bootstrap.yaml         # Minimal infra config (~10 lines)
  tools.yaml             # YAML fallback when DB is unavailable

migrations/
  001_tools_schema.sql   # tools, tool_configs, credentials tables
```

Future tools (implement when needed, not now):
- `email/gmail.py`, `queue/sqs.py`, `queue/rabbitmq.py`, `queue/kafka.py`
- `data/postgres.py`, `data/mysql.py`, `sms/twilio.py`
- `desktop/screen.py`, `network/sdn.py`, `stream/audio.py`, `stream/video.py`

---

## HTTP Server Tool (`src/tools_catalog/api/http_server.py`)

Universal source for TUIs, scripts, curl, and any HTTP client.

```python
from src.plugins.base import Tool, Envelope, ToolContext
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import asyncio, uvicorn, json, redis.asyncio as aioredis


class HttpServerTool(Tool):
    type = "api"
    name = "http_server"
    description = "Local HTTP+SSE server for TUIs, scripts, and curl"
    listen = True
    node = "genesis"  # only runs on genesis node

    def initialize(self, config):
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 8000)
        self.api_key = config.get("api_key", "")
        self.redis_url = config.get("redis_url", "redis://localhost:6379")
        self.app = FastAPI()
        self._on_message = None
        self._redis = None

    def get_tool_schemas(self):
        return []  # listener only — agent never calls this

    async def call_tool(self, tool_name, args, ctx):
        pass

    async def start_listener(self, on_message):
        self._on_message = on_message
        self._redis = aioredis.from_url(self.redis_url)
        self._setup_routes()
        config = uvicorn.Config(self.app, host=self.host, port=self.port,
                                log_level="info")
        server = uvicorn.Server(config)
        asyncio.create_task(server.serve())

    def _setup_routes(self):

        @self.app.post("/task")
        async def submit_task(request: Request):
            """Async path: returns task_id immediately."""
            body = await request.json()
            envelope = self._body_to_envelope(body)
            task_id = await self._on_message(envelope)
            return {"task_id": task_id}

        @self.app.post("/task/run")
        async def run_task(request: Request):
            """Sync path: blocks until task completes, returns full result."""
            body = await request.json()
            envelope = self._body_to_envelope(body)
            task_id = await self._on_message(envelope)
            result = await self._wait_for_result(task_id)
            return result

        @self.app.get("/task/{task_id}/stream")
        async def stream_task(task_id: str):
            """SSE stream of progress events."""
            return EventSourceResponse(self._sse_generator(task_id))

        @self.app.get("/task/{task_id}/files/{filename}")
        async def download_file(task_id: str, filename: str):
            # Serve artifact files
            ...

        @self.app.get("/tasks")
        async def list_tasks():
            # Return recent task history from scheduler
            ...

        # --- Tool management API ---

        @self.app.post("/tools/register")
        async def register_tool(request: Request):
            """Register a new tool instance in the database."""
            body = await request.json()
            # INSERT into tools + tool_configs + credentials tables
            # Invalidate Redis cache
            # Broadcast reload
            ...

        @self.app.patch("/tools/{name}/enable")
        async def enable_tool(name: str):
            # UPDATE tools SET enabled=true WHERE name=...
            ...

        @self.app.patch("/tools/{name}/disable")
        async def disable_tool(name: str):
            # UPDATE tools SET enabled=false WHERE name=...
            ...

        @self.app.get("/tools")
        async def list_tools():
            # SELECT name, type, enabled, listen FROM tools ORDER BY type, name
            ...

    def _body_to_envelope(self, body: dict) -> Envelope:
        return Envelope(
            source=body.get("source", "http"),
            task_description=body.get("description", ""),
            payload=body.get("payload"),
            content_type=body.get("content_type", "text/plain"),
            reply_to=body.get("source", "http"),
            metadata=body.get("context", {}),
        )

    async def _wait_for_result(self, task_id: str) -> dict:
        """Subscribe to Redis channel, buffer until done event."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"task:{task_id}:events")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                event = json.loads(msg["data"])
                if event.get("event") in ("done", "error"):
                    return event.get("data", {})
        finally:
            await pubsub.unsubscribe()

    async def _sse_generator(self, task_id: str):
        """Yield SSE events from Redis pub/sub."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"task:{task_id}:events")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                event = json.loads(msg["data"])
                yield {"event": event.get("event", "progress"),
                       "data": json.dumps(event.get("data", {}))}
                if event.get("event") in ("done", "error"):
                    break
        finally:
            await pubsub.unsubscribe()


tool_class = HttpServerTool
```

---

## MCP Bridge (`src/plugins/mcp_bridge.py`)

Wraps any MCP server (stdio or HTTP) as a Tool. Each MCP server gets its own entry
in the tools DB — the bridge handles the protocol translation.

```python
from src.plugins.base import Tool, ToolContext
import asyncio, json


class MCPBridgeTool(Tool):
    type = "mcp"
    name = "mcp_bridge"
    description = "Wraps an external MCP server as a tool"
    node = "worker"

    def initialize(self, config):
        self.transport = config["transport"]    # "stdio" or "http"
        self.command = config.get("command")     # for stdio: shell command
        self.url = config.get("url")             # for http: server URL
        self._process = None
        self._tools_cache = None
        self._request_id = 0

    def get_tool_schemas(self) -> list[dict]:
        """Connect to MCP server, call tools/list, convert to OpenAI format."""
        if self._tools_cache is None:
            self._tools_cache = asyncio.get_event_loop().run_until_complete(
                self._fetch_tools()
            )
        return self._tools_cache

    async def call_tool(self, tool_name, args, ctx) -> str:
        """Call MCP server's tools/call and return the result."""
        response = await self._send_jsonrpc("tools/call", {
            "name": tool_name,
            "arguments": args
        })
        # Extract text content from MCP response
        content = response.get("result", {}).get("content", [])
        texts = [c["text"] for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(response)

    async def _fetch_tools(self) -> list[dict]:
        """Get tool list from MCP server, convert to OpenAI schema format."""
        await self._ensure_connected()
        response = await self._send_jsonrpc("tools/list", {})
        mcp_tools = response.get("result", {}).get("tools", [])
        schemas = []
        for t in mcp_tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                }
            })
        return schemas

    async def _ensure_connected(self):
        if self.transport == "stdio" and self._process is None:
            self._process = await asyncio.create_subprocess_exec(
                *self.command.split(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Send initialize handshake
            await self._send_jsonrpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "orchestrator", "version": "1.0"}
            })

    async def _send_jsonrpc(self, method, params) -> dict:
        self._request_id += 1
        msg = json.dumps({"jsonrpc": "2.0", "id": self._request_id,
                          "method": method, "params": params})
        if self.transport == "stdio":
            self._process.stdin.write(f"{msg}\n".encode())
            await self._process.stdin.drain()
            line = await self._process.stdout.readline()
            return json.loads(line)
        # HTTP transport: POST to self.url
        ...


tool_class = MCPBridgeTool
```

**Google Drive via MCP:**
```bash
# Register in DB or tools.yaml:
# name: google_drive
# module: src.plugins.mcp_bridge
# config:
#   transport: stdio
#   command: "npx -y @modelcontextprotocol/server-gdrive"
```

---

## Internal ToolBuilder (`src/tool_builder/builder.py`)

NOT agent-facing. The worker catches `ToolNotFound` and invokes this internally.
Uses a high-reasoning model (claude-opus, GLM) to write the missing tool.

```python
class ToolBuilder:
    def __init__(self, config: dict):
        self.model = config["model"]          # "claude-opus-4-6"
        self.catalog_path = config["tools_catalog_path"]
        self.max_retries = config.get("max_retries", 2)

    async def build(self, tool_name: str, task_context: str) -> str:
        """Write a new tool plugin. Returns registered tool name on success."""
        # 1. Call high-reasoning model with:
        #    - The Tool ABC code (exact)
        #    - An example tool (e.g. gmail.py)
        #    - What the missing tool should do (inferred from tool_name + task)
        # 2. Validate generated code (see validator.py)
        # 3. Write to src/tools_catalog/{type}/{name}.py
        # 4. INSERT into tools table, tool_configs table
        # 5. Invalidate Redis cache
        # 6. registry.register(new_tool_instance)
        # 7. Return tool_name
        ...
```

### Validator (`src/tool_builder/validator.py`)

Before registering a generated tool, validate:
- File parses as valid Python (ast.parse)
- Contains a class that subclasses Tool
- Class has `get_tool_schemas()` and `call_tool()` methods
- Module-level `tool_class = ClassName` exists
- No dangerous imports: `os.system`, `subprocess.call`, `eval`, `exec`, `__import__`
  (allow `subprocess.run` only — needed for tools that wrap CLI commands)
- No network calls in module-level code (only in methods)

### Worker integration

```python
# In worker.py ReAct tool execution loop:
try:
    result = await registry.call_tool(tool_name, args, ctx)
except ToolNotFound:
    built = await tool_builder.build(tool_name, task_context=task_description)
    result = await registry.call_tool(f"{built}__{tool_name}", args, ctx)
```

---

## Integration Changes to Existing Code

### `src/execution/worker/worker.py` (~15 lines changed)

```python
# REMOVE these imports:
from src.execution.worker.tools import get_tool_schemas, get_tool_fn

# ADD these imports:
from src.plugins.loader import load_tools
from src.plugins.registry import registry, ToolNotFound
from src.plugins.base import ToolContext
from src.tool_builder.builder import ToolBuilder

# At worker startup:
load_tools("config/bootstrap.yaml", node="worker")
tool_builder = ToolBuilder(config["tool_builder"])

# Replace tool schema injection (in agent_plan node):
# envelope.tool_scope restricts which tools the agent sees for this task.
# Example: gmail_work listener sets tool_scope=["gmail_work", "shell", "filesystem"]
# so the agent can't accidentally use gmail_personal.
tool_schemas = registry.get_all_tool_schemas(
    specialization=detected_spec,
    tool_scope=envelope.tool_scope
)

# Replace tool execution (in tool_executor node):
ctx = ToolContext(workspace_dir=workspace, task_id=task_id, envelope=envelope)
try:
    result = await registry.call_tool(tool_name, args, ctx)
except ToolNotFound:
    await tool_builder.build(tool_name, task_context=task_description)
    result = await registry.call_tool(tool_name, args, ctx)
```

### `src/genesis/orchestrator/scheduler.py` (~20 lines changed)

```python
# REMOVE hardcoded Telegram delivery:
#   if source == "telegram": await self.notifier.send_message(...)

# ADD registry-based delivery:
from src.plugins.registry import registry

async def _deliver_result(self, envelope, result, artifacts):
    source_tool = registry.get(envelope.source)
    if source_tool:
        await source_tool.deliver_result(envelope, result, artifacts)
```

### `src/genesis/main.py`

```python
from src.plugins.loader import load_tools
from src.plugins.registry import registry

load_tools("config/bootstrap.yaml", node="genesis")

for tool in registry.get_listeners():
    await tool.start_listener(on_message=scheduler.submit_task)
```

---

## Result Delivery

Each tool overrides `deliver_result()` to send output back to its source:

| Source tool | How result is delivered |
|------------|----------------------|
| `telegram` | `chat_send()` — message back to same chat |
| `http_server` | Redis pub/sub → SSE stream closes or sync response returns |
| `sqs_orders` | `queue_send()` to reply queue, `queue_delete_message()` to ack |
| `postgres_tasks` | `UPDATE tasks SET status='done', result=... WHERE id=...` |
| `sms_twilio` | `sms_send()` — reply SMS to originating number |

---

## YAML Fallback (`config/tools.yaml`)

Used when DB is unavailable (first boot, offline, dev). Same structure as DB but in YAML.
The `tool_builder` config is a top-level key, NOT inside `tools:`.

```yaml
tool_builder:
  model: claude-opus-4-6
  max_retries: 2
  tools_catalog_path: src/tools_catalog

tools:
  http_server:
    enabled: true
    type: api
    listen: true
    node: genesis
    module: src.tools_catalog.api.http_server
    config:
      host: 127.0.0.1
      port: 8000
      api_key: ${API_KEY}
      redis_url: ${REDIS_URL}

  telegram:
    enabled: true
    type: chat
    listen: true
    node: both
    module: src.tools_catalog.chat.telegram
    config:
      bot_token: ${TELEGRAM_BOT_TOKEN}
      chat_id: ${TELEGRAM_CHAT_ID}

  shell:
    enabled: true
    type: code
    node: worker
    module: src.tools_catalog.code.shell
    config:
      timeout_seconds: 120

  filesystem:
    enabled: true
    type: code
    node: worker
    module: src.tools_catalog.code.filesystem
    config: {}

  web:
    enabled: true
    type: code
    node: worker
    module: src.tools_catalog.code.web
    config: {}

  git:
    enabled: true
    type: code
    node: worker
    module: src.tools_catalog.code.git
    config: {}

  image:
    enabled: true
    type: media
    node: worker
    module: src.tools_catalog.media.image
    config: {}

  http_client:
    enabled: true
    type: webhook
    node: worker
    module: src.tools_catalog.webhook.http_client
    config: {}

  google_drive:
    enabled: false
    type: mcp
    node: worker
    module: src.plugins.mcp_bridge
    config:
      transport: stdio
      command: "npx -y @modelcontextprotocol/server-gdrive"
```

---

## Implementation Order

### Phase 1 — Foundation
1. `src/plugins/base.py` — Tool, Envelope, ToolContext
2. `src/plugins/registry.py` — ToolRegistry with O(1) lookup + specialization filter
3. `src/plugins/loader.py` — DB-backed with YAML fallback, env var resolution
4. `config/bootstrap.yaml`
5. `config/tools.yaml` (YAML fallback)
6. `migrations/001_tools_schema.sql`

### Phase 2 — Migrate existing tools
7. `src/tools_catalog/code/shell.py` — from tools.py `shell_exec`
8. `src/tools_catalog/code/filesystem.py` — from tools.py file operations
9. `src/tools_catalog/code/web.py` — from tools.py web operations
10. `src/tools_catalog/code/git.py` — from tools.py git operations
11. `src/tools_catalog/media/image.py` — from tools.py `generate_image`
12. `src/tools_catalog/chat/telegram.py` — wraps TelegramMonitor + TelegramNotifier

### Phase 3 — New tools
13. `src/tools_catalog/api/http_server.py` — HTTP+SSE source + tool mgmt API
14. `src/tools_catalog/webhook/http_client.py` — http_request tool
15. `src/plugins/mcp_bridge.py` — MCP server adapter (+ Google Drive config)

### Phase 4 — Wire into existing code
16. Update `worker.py` — use registry for tool schemas and execution
17. Update `scheduler.py` — use registry for result delivery
18. Update `genesis/main.py` — load tools and start listeners

### Phase 5 — ToolBuilder
19. `src/tool_builder/builder.py`
20. `src/tool_builder/validator.py`
21. `src/tool_builder/prompt.py`

### Future (implement when actually needed)
- Email, SMS, SQS, RabbitMQ, Kafka, Postgres listener, MySQL
- Desktop ambient, SDN, audio/video streaming, phone
- MessageBus abstraction (when multiple subscribers exist)

---

## What NOT to Change

- `TelegramMonitor` and `TelegramNotifier` internals — wrap them, don't rewrite
- Temporal workflow definition structure
- `KnowledgeBaseClient`, `HybridMemoryStore`
- `config/settings.yaml`, `config/profiles.yaml`, `config/jobs.yaml`
- Existing tests
