# AI Orchestrator TODO List

### Features
- [x] Multi-Agent Orchestrator with dynamic task decomposition and parallel execution.
- [x] Self-healing recovery system — detects missing-tool failures, implements the tool via coder agent, retries the original task. Includes infinite-loop guard and real-time recovery notifications to task source (Telegram/CLI/TUI).
- [x] Generic recovery coder agent — analyzes any failure, builds whatever tool is needed (not hardcoded to GIF), installs its own dependencies via shell_exec, tests before finalizing. Dynamic import scanner handles arbitrary packages.
- [ ] Implement advanced error recovery protocols for long-running Temporal task executions.
- [ ] Integration with real SOTA media APIs (Luma Dream Machine, Suno v4, Sora) for `generate_video` and `generate_audio` tools.
- [ ] Add agent "Co-Pilot" mode where agents can request human intervention for ambiguous tasks.
- [ ] Add timeline graphs or latency heatmaps to the Observability Dashboard for worker nodes.
- [ ] Introduce full-text search across the historical task database (Qdrant).

### Fixes
- [x] Resolved circular import and Redundant Prometheus metrics initialization in multi-agent worker environments.
- [x] Fixed `duckduckgo_search` package import compatibility.
- [x] Fixed all invalid `gemini-3-*` model IDs in `profiles.yaml` — replaced with `gemini-2.5-flash`.
- [x] Fixed `SAFE_FALLBACK_MODEL` routing through OpenRouter without a key — now uses Google native client.
- [x] Fixed `_call_google` not supporting function calling — rewrote with full tool schema conversion and function call response parsing.
- [x] Removed `_run_media_direct` bypass that violated the multi-agent orchestrator architecture.
- [x] Fixed planner over-decomposing single-step tasks as `coordinated_team` — tightened decision rules.
- [ ] Address strict mode violations and timing sensitivities in the Playwright integration tests.
- [ ] Optimize the memory decay loops in `hybrid_store.py` to prevent stale task metadata accumulation.
- [ ] Prevent native worker processes from running on the genesis node (add a startup check or systemd guard).

---

## Modular Tool Plugin System — Implementation Stories

Stories are independent and assignable to different coding models in parallel.
Each story lists inputs (reads), outputs (creates), and interface contract.

### Completed
- [x] **Phase 1** — Foundation: `src/plugins/base.py`, `registry.py`, `loader.py`, `config/bootstrap.yaml`, `config/tools.yaml`, `migrations/001_tools_schema.sql`, `scripts/migrate_yaml_to_db.py`
- [x] **Phase 2** — Migrate existing tools: `tools_catalog/code/shell.py`, `filesystem.py`, `web.py`, `git.py`, `tools_catalog/media/image.py`, `tools_catalog/chat/telegram.py`

---

### Wave 1 — Fully Independent (run all in parallel)

#### Story 1.1 — API: Tool CRUD endpoints
- [x] **File:** `src/web/api/tools.py`
- **Also create:** `src/web/__init__.py`, `src/web/api/__init__.py`
- **Reads:** `src/plugins/loader.py` (functions: `_load_from_yaml`, `encrypt_credential`, `invalidate_tool_cache`, `_resolve_env_vars`), `config/tools.yaml`
- **Exports:** `tools_router` (FastAPI `APIRouter(prefix="/api")`)
- **Endpoints:**
  - `GET /api/tools` → list all tools with config (credentials masked as "••••••")
  - `POST /api/tools` → register new tool instance `{name, type, module, node, listen, config, credentials}`
  - `GET /api/tools/{name}` → single tool detail
  - `PUT /api/tools/{name}` → update config/credentials
  - `DELETE /api/tools/{name}` → remove tool + cascade
  - `PATCH /api/tools/{name}/enable` → set enabled=true
  - `PATCH /api/tools/{name}/disable` → set enabled=false
- **Storage:** YAML fallback (read/write `config/tools.yaml`). DB path via asyncpg when available.
- **After mutation:** call `await invalidate_tool_cache()`

#### Story 1.2 — API: Config endpoints (YAML read/write)
- [x] **File:** `src/web/api/config.py`
- **Reads:** `config/profiles.yaml`, `config/settings.yaml`, `config/jobs.yaml`, `config/cluster_nodes.yaml`
- **Exports:** `config_router` (FastAPI `APIRouter(prefix="/api/config")`)
- **Endpoints:**
  - `GET/PUT /api/config/routing` — profiles.yaml `task_routing` section
  - `GET /api/config/models` — profiles.yaml `models` list (read-only)
  - `GET/PUT /api/config/specializations` — profiles.yaml `specializations`
  - `GET/PUT /api/config/agent-defaults` — jobs.yaml `agent_defaults`
  - `GET/PUT /api/config/infrastructure` — settings.yaml (full)
  - `GET/PUT /api/config/cluster` — cluster_nodes.yaml (full)
- **Write pattern:** read existing YAML → merge with request body → write to temp file → `os.replace()` (atomic)

#### Story 1.3 — API: Health status endpoint
- [x] **File:** `src/web/api/status.py`
- **Reads:** `config/settings.yaml` (hosts/ports via `src.config.load_settings()`)
- **Exports:** `status_router` (FastAPI `APIRouter(prefix="/api")`)
- **Endpoint:** `GET /api/status` → `{"temporal": {"status":"up","latency_ms":12}, "qdrant": {...}, "redis": {...}, "lmstudio": {...}, "workers": [...]}`
- **Checks:** TCP connect with 3s timeout (`asyncio.open_connection`), Redis PING, worker SSH port check

#### Story 3.2 — http_client tool (outbound HTTP requests)
- [x] **Files:** `src/tools_catalog/webhook/__init__.py`, `src/tools_catalog/webhook/http_client.py`
- **Reads:** `src/plugins/base.py` (Tool ABC, ToolContext)
- **Exports:** `tool_class = HttpClientTool`
- **Agent function:** `http_request(method, url, headers?, body?, timeout?)` → `{"status_code", "headers", "body"}`
- **Uses:** `httpx.AsyncClient` (already in requirements)
- **Truncate** response body to 50KB. Sanitize API keys from output.

#### Story 3.3 — MCP bridge tool
- [x] **File:** `src/plugins/mcp_bridge.py`
- **Reads:** `src/plugins/base.py` (Tool ABC)
- **Exports:** `tool_class = MCPBridgeTool`
- **Config:** `{transport: "stdio", command: "npx -y @modelcontextprotocol/server-gdrive"}`
- **Protocol:** JSON-RPC over stdin/stdout
  - On init: send `initialize` handshake
  - `get_tool_schemas()` → call `tools/list`, convert MCP `inputSchema` to OpenAI `parameters` format, cache result
  - `call_tool(name, args, ctx)` → call `tools/call`, extract text content from response
- **Process:** `asyncio.create_subprocess_exec(*command.split(), stdin=PIPE, stdout=PIPE)`

---

### Wave 2 — Depends on Wave 1

#### Story 1.4 — Admin router + base template
- [x] **Files:** `src/web/admin.py`, `src/web/templates/base.html`
- **Imports:** `tools_router` from 1.1, `config_router` from 1.2, `status_router` from 1.3
- **Exports:** `create_admin_router()` → FastAPI `APIRouter` with all sub-routers + UI page routes
- **`admin.py`:** defines `/ui/`, `/ui/tools`, `/ui/tools/new`, `/ui/tools/{name}`, `/ui/models`, `/ui/settings` routes that render Jinja2 templates
- **`base.html`:** Tailwind CDN (`<script src="https://cdn.tailwindcss.com">`), HTMX CDN (`<script src="https://unpkg.com/htmx.org@2.0.4">`), dark sidebar nav (Dashboard, Tools, Models, Settings), `{% block content %}`, toast div

#### Story 3.1 — http_server tool (task submission + SSE)
- [x] **Files:** `src/tools_catalog/api/__init__.py`, `src/tools_catalog/api/http_server.py`
- **Reads:** `src/plugins/base.py`, `src/web/admin.py` (mounts admin router)
- **Exports:** `tool_class = HttpServerTool`
- **Config:** `{host, port, api_key, redis_url}`
- **Tool attrs:** `type="api"`, `listen=True`, `node="genesis"`, `get_tool_schemas()→[]`
- **`start_listener(on_message)`:** creates FastAPI app, mounts admin router, adds task endpoints, runs uvicorn
- **Task endpoints:**
  - `POST /task` → async, returns `{"task_id"}`
  - `POST /task/run` → sync, blocks on Redis pub/sub until done
  - `GET /task/{id}/stream` → SSE via `sse_starlette.EventSourceResponse`
  - `GET /task/{id}/files/{filename}` → artifact download
- **Redis:** subscribe to `task:{id}:events` channel for SSE and sync wait

---

### Wave 3 — Depends on Wave 2 (all pages are independent of each other)

#### Story 1.5 — Dashboard page
- [x] **File:** `src/web/templates/dashboard.html`
- Extends `base.html`. Cards: tool counts (total/enabled/listeners/disabled). Health dots via `hx-get="/api/status"`. Quick action buttons.

#### Story 1.6 — Tool list page
- [x] **File:** `src/web/templates/tools/list.html`
- Extends `base.html`. Table of tools. Enabled toggle via HTMX PATCH. Delete with confirm. Clone link. "Add Tool" button.

#### Story 1.7 — Tool add/edit form page
- [x] **File:** `src/web/templates/tools/form.html`
- Extends `base.html`. Reused for new + edit. Dynamic key-value config/credential rows. HTMX submit to `/api/tools`.

#### Story 1.8 — Model routing page
- [x] **File:** `src/web/templates/models/routing.html`
- Extends `base.html`. Routing table with model/provider dropdowns. Specialization collapsibles with allowed_tools checkboxes. Save via HTMX PUT.

#### Story 1.9 — Settings page (agent defaults, infra, cluster)
- [x] **File:** `src/web/templates/settings/general.html`
- Extends `base.html`. Three tabs: Agent Defaults (number inputs), Infrastructure (env dropdown + host/port fields), Cluster Nodes (table + health check).

#### Story 1.10 — Enable tools in tools.yaml + smoke test
- [x] Enable `http_server` in `config/tools.yaml`
- Verify: `curl http://localhost:8000/ui/` renders, `/api/tools` returns JSON, `/api/status` returns health

---

### Dependency Graph
```
Wave 1 (parallel):  1.1  1.2  1.3  3.2  3.3
                      │    │    │
                      ▼    ▼    ▼
Wave 2:             1.4 ◄─────────  3.1 (mounts 1.4)
                      │               │
                      ▼               ▼
Wave 3 (parallel):  1.5  1.6  1.7  1.8  1.9  1.10
```

---

### Phase 3 — New tools (Completed in Wave 1-3)
- [x] `src/tools_catalog/api/http_server.py` — HTTP+SSE source + tool mgmt API
- [x] `src/tools_catalog/webhook/http_client.py` — http_request tool
- [x] `src/plugins/mcp_bridge.py` — MCP server adapter

### Phase 4 — Wire into existing code
- [x] 16. Update `worker.py` — use registry for tool schemas and execution
- [x] 17. Update `scheduler.py` — use registry for result delivery
- [x] 18. Update `genesis/main.py` — load tools and start listeners

---

## Telegram Media Handling — Completed 2026-03-25

### Implementation Summary

**Files Created:**
- `config/media.yaml` — Configurable model tiers for transcription/vision
- `src/tools_catalog/media/audio.py` — `transcribe_audio` tool (Groq/OpenAI/Gemini)
- `src/tools_catalog/media/vision.py` — `analyze_image` tool (Gemini/GPT-4V/Claude)

**Files Modified:**
- `src/genesis/orchestrator/telegram_monitor.py` — Added media handlers
- `src/execution/worker/worker.py` — Added media envelope detection
- `config/tools.yaml` — Registered media tools

### Features
- [x] Voice message transcription (OGG/OGA → text via Groq Whisper <2s)
- [x] Photo analysis (JPEG → description via Gemini Flash <3s)
- [x] Audio file processing (MP3, WAV, M4A)
- [x] Configurable model tiers in `config/media.yaml`
- [x] Auto-injection of media tools based on content type
- [x] Real-time status updates in Telegram chat
- [x] /do command retained for explicit task submission

### Bug Fix
- Fixed `/do` command: changed `cmd.startswith("/do ")` to `command.startswith("/do ")`

### Architecture
```
Telegram → Genesis (download) → Temporal → Worker (transcribe/analyze) → Response
```

### Latency Targets
| Media Type | Model | Target |
|------------|-------|--------|
| Voice | Groq Whisper | <2s |
| Photo | Gemini Flash | <3s |
| Audio | GPT-4o-mini | <10s |
