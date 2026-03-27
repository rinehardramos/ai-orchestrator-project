import asyncio
import base64
import mimetypes
import os
import uuid
import json
import yaml
import logging
from typing import TypedDict, Annotated, Any
from datetime import timedelta

# Temporal
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

# Langgraph
from langgraph.graph import StateGraph, START, END

# opik
import time
try:
    from opik import track
    OPIK_AVAILABLE = True
except ImportError:
    OPIK_AVAILABLE = False
    def track(**kwargs):
        def decorator(fn):
            return fn
        return decorator

# Local imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
from src.shared.memory.knowledge_base import KnowledgeBaseClient
from src.shared.memory.decay_workflow import BeliefDecayWorkflow, apply_belief_decay
from src.config import load_settings
from src.execution.worker.sandbox import create_workspace, cleanup_workspace
from src.execution.worker.tools import get_tool_schemas, get_tool_fn, TOOL_REGISTRY
from src.execution.worker.prompts import build_system_prompt

# Plugin system imports
try:
    from src.plugins.loader import load_tools, load_tools_sync
    from src.plugins.registry import registry, ToolNotFound
    from src.plugins.base import ToolContext
    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False
    ToolContext = None

from src.execution.worker.model_router import ModelRouter, TaskType
from src.execution.worker.embeddings import get_embedder

# Budget tracking
try:
    from src.shared.budget.tracker import budget_tracker
    import asyncpg
    import redis.asyncio as redis
    BUDGET_TRACKING_ENABLED = True
except ImportError:
    BUDGET_TRACKING_ENABLED = False
    budget_tracker = None

# opik tracing moved to top

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Worker")

# --- Global Config & Memory Store ---
config = load_settings()
temp_cfg = config.get("temporal", {})
qdrant_cfg = config.get("qdrant", {})
redis_cfg = config.get("redis", {})

# Initialize memory store - prefer environment variables for Docker
qdrant_url = os.environ.get("QDRANT_URL") or f"http://{qdrant_cfg.get('host', 'localhost')}:{qdrant_cfg.get('port', 6333)}"
redis_url = os.environ.get("REDIS_URL") or f"redis://{redis_cfg.get('host', 'localhost')}:{redis_cfg.get('port', 6379)}"

memory_store = HybridMemoryStore(
    redis_url=redis_url,
    qdrant_url=qdrant_url
)

# Load plugin tools at startup
_tools_loaded = False
_last_config_check = 0

async def _ensure_tools_loaded():
    global _tools_loaded, _last_config_check
    if not _tools_loaded and PLUGINS_AVAILABLE:
        try:
            await load_tools("config/bootstrap.yaml", node="worker")
            _tools_loaded = True
            logger.info(f"Loaded {len(registry._tools)} tools from plugin registry")
            from src.execution.worker.tools import _build_plugin_fn_map
            _build_plugin_fn_map()
        except Exception as e:
            logger.warning(f"Could not load plugin tools: {e}")

def _check_config_reload():
    """Check if config has changed and reload if needed."""
    global _last_config_check
    import time
    now = time.time()
    if now - _last_config_check > 30:
        _last_config_check = now
        try:
            if registry.check_and_reload_config():
                from src.execution.worker.tools import _build_plugin_fn_map
                _build_plugin_fn_map()
                logger.info("Config reloaded, tool function map rebuilt")
        except Exception as e:
            logger.warning(f"Config reload check failed: {e}")


def _get_knowledge_collections() -> tuple:
    """Get knowledge and insights collection names from database config."""
    try:
        from src.config_db import get_loader
        loader = get_loader()
        config = loader.load_namespace("knowledge") or {}
        return (
            config.get("knowledge_collection", "knowledge_v1"),
            config.get("insights_collection", "agent_insights_v4")
        )
    except Exception:
        return ("knowledge_v1", "agent_insights_v4")

# --- Agent Defaults (from jobs.yaml) ---
def load_agent_defaults() -> dict:
    defaults = {"max_tool_calls": 50, "max_cost_usd": 0.50, "shell_timeout_seconds": 120, "activity_timeout_minutes": 30}
    try:
        from src.config_db import get_loader
        jobs_config = get_loader().load_namespace("jobs")
        if jobs_config:
            defaults.update(jobs_config)
    except Exception as e:
        log.error(f"Could not load agent defaults from DB: {e}")
        # Use hardcoded defaults if DB unavailable, but log an error
    return defaults

AGENT_DEFAULTS = load_agent_defaults()

# --- Model Router (config-driven, OpenRouter primary / LiteLLM for local in Phase 3) ---
router = ModelRouter()

def generate_content_with_tools(messages: list[dict], task_type: TaskType = TaskType.AGENT_STEP, specialization: str = "general") -> tuple[Any, float]:
    """
    Call LLM with tool schemas. Returns (response_message, cost_usd).
    The response_message may contain tool_calls or plain content.
    """
    tool_schemas = get_tool_schemas(specialization)
    errors = []
    
    # Try the specific task type first
    try:
        return router.call_llm(messages, task_type, tool_schemas)
    except Exception as e:
        errors.append(f"{task_type.value}: {str(e)}")
        logger.warning(f"Router failed for primary task_type '{task_type.value}': {e}")
        
        # If it's an Auth error (401), don't bother with local fallbacks as they likely won't help or will use wrong model
        if "401" in str(e) or "Unauthorized" in str(e):
            raise ValueError(f"Authentication failed for {task_type.value}. Please check your API keys. Error: {e}")

        # Fallback logic
        fallback_types = [TaskType.ANALYSIS, TaskType.AGENT_STEP]
        for fallback_type in fallback_types:
            if fallback_type == task_type:
                continue
            try:
                logger.info(f"Attempting fallback to task_type={fallback_type.value}...")
                result = router.call_llm(messages, fallback_type, tool_schemas)
                logger.info(f"Tool-call fallback succeeded with task_type={fallback_type.value}")
                return result
            except Exception as fe:
                errors.append(f"{fallback_type.value}: {str(fe)}")
                continue
        
        error_summary = " | ".join(errors)
        raise ValueError(f"All models failed for tool call. History: {error_summary}")



# ──────────────────────────────────────────────
# AGENTIC PIPELINE (ReAct loop with tools)
# ──────────────────────────────────────────────

class AgenticState(TypedDict):
    messages: list[dict]
    workspace_dir: str
    tool_call_count: int
    max_tool_calls: int
    max_cost_usd: float
    total_cost_usd: float
    model_id: str
    provider: str
    specialization: str
    artifacts: list[str]
    progress_log: list[str]
    error: str
    status: str
    summary: str


def _fetch_qdrant_context(task_description: str) -> str:
    """Retrieve relevant past insights from Qdrant for the agent system prompt."""
    _, insights_collection = _get_knowledge_collections()
    try:
        vector = get_embedder().embed(task_description)
        results = memory_store.query_l2(insights_collection, vector, limit=3)
        if results:
            entries = []
            for r in results:
                payload = r.payload or {}
                if r.score > 0.5:
                    entries.append(f"- [{r.score:.2f}] {payload.get('content', '')[:300]}")
            if entries:
                return "\n".join(entries)
    except Exception as e:
        logger.warning(f"Qdrant context fetch failed: {e}")
    return "No relevant past insights found."


@track(name="agent_plan")
def agent_plan(state: AgenticState) -> AgenticState:
    """Initial node: build system prompt and seed the conversation."""
    qdrant_context = _fetch_qdrant_context(
        state["messages"][0]["content"] if state["messages"] else ""
    )
    system_prompt = build_system_prompt(
        workspace_dir=state["workspace_dir"],
        task_description=state["messages"][0]["content"] if state["messages"] else "",
        budget_remaining=state["max_cost_usd"] - state["total_cost_usd"],
        steps_remaining=state["max_tool_calls"] - state["tool_call_count"],
        max_steps=state["max_tool_calls"],
        qdrant_context=qdrant_context,
        specialization=state.get("specialization", "general"),
    )
    # Prepend system message
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    return {"messages": messages, "progress_log": ["plan: system prompt built"]}


@track(name="agent_step")
def agent_step(state: AgenticState) -> AgenticState:
    """Core agent node: call LLM, get response (may include tool_calls or final text)."""
    _check_config_reload()
    
    if state["total_cost_usd"] >= state["max_cost_usd"]:
        logger.warning(f"Cost budget exceeded (${state['total_cost_usd']:.4f} >= ${state['max_cost_usd']:.4f}), forcing completion")
        return {
            "messages": state["messages"] + [{"role": "assistant", "content": "Budget exceeded. Summarizing progress so far."}],
            "status": "budget_exceeded",
            "progress_log": state["progress_log"] + ["agent: budget exceeded, forcing summarize"],
        }

    if state["tool_call_count"] >= state["max_tool_calls"]:
        logger.warning(f"Tool call limit reached ({state['max_tool_calls']}), forcing completion")
        return {
            "messages": state["messages"] + [{"role": "assistant", "content": "Tool call limit reached. Summarizing progress so far."}],
            "status": "limit_reached",
            "progress_log": state["progress_log"] + ["agent: tool call limit reached"],
        }

    try:
        task_description = ""
        for msg in state["messages"]:
            if msg.get("role") == "user":
                task_description = msg.get("content", "")
                break
        detected_type = router.detect_task_type(task_description)
        response_msg, cost = generate_content_with_tools(
            state["messages"],
            task_type=detected_type,
            specialization=state.get("specialization", "general")
        )
        new_cost = state["total_cost_usd"] + cost

        # Heartbeat with structured progress
        progress = {
            "step": state["tool_call_count"],
            "max_steps": state["max_tool_calls"],
            "cost_usd": round(new_cost, 6),
            "phase": "agent_step",
        }
        try:
            activity.heartbeat(json.dumps(progress))
        except Exception:
            pass

        # Convert response to dict for message history
        msg_dict = {"role": "assistant", "content": response_msg.content or ""}
        if hasattr(response_msg, "tool_calls") and response_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in response_msg.tool_calls
            ]

        return {
            "messages": state["messages"] + [msg_dict],
            "total_cost_usd": new_cost,
            "progress_log": state["progress_log"] + [f"agent: LLM call (cost=${cost:.6f})"],
        }
    except Exception as e:
        logger.error(f"Agent LLM call failed: {e}")
        return {
            "messages": state["messages"] + [{"role": "assistant", "content": f"LLM call failed: {e}"}],
            "error": str(e),
            "status": "error",
            "progress_log": state["progress_log"] + [f"agent: ERROR - {e}"],
        }


@track(name="tool_executor")
def tool_executor(state: AgenticState) -> AgenticState:
    """Execute tool calls from the last assistant message and append results."""
    last_msg = state["messages"][-1]
    tool_calls = last_msg.get("tool_calls", [])
    if not tool_calls:
        return state

    new_messages = []
    new_count = state["tool_call_count"]
    new_artifacts = list(state.get("artifacts", []))
    new_log = list(state["progress_log"])
    task_complete_triggered = False
    summary = state.get("summary", "")

    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            args = {}

        new_count += 1

        # Try plugin registry first (namespaced functions like gmail_blackopstech047__email_read_inbox)
        result_str = None
        if PLUGINS_AVAILABLE:
            try:
                # Ensure tools are loaded (sync version)
                if not registry._tools:
                    load_tools_sync(node="worker")
                
                # Check if this is a namespaced function name
                if "__" in fn_name and fn_name in registry._fn_lookup:
                    instance_name = registry._fn_lookup[fn_name]
                    tool = registry._tools[instance_name]
                    raw_fn_name = fn_name.split("__", 1)[1]
                    
                    # Get method mapping from tool
                    method_map = getattr(tool, '_method_map', {})
                    method_name = method_map.get(raw_fn_name)
                    
                    if method_name and hasattr(tool, method_name):
                        result_str = getattr(tool, method_name)(**args)
                    else:
                        # Fallback to call_tool async method
                        from src.plugins.base import ToolContext
                        ctx = ToolContext(workspace_dir=state["workspace_dir"], task_id="", envelope=None)
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        result_str = loop.run_until_complete(tool.call_tool(raw_fn_name, args, ctx))
                else:
                    # Legacy non-namespaced lookup
                    tool_fn = get_tool_fn(fn_name)
                    if tool_fn is None:
                        result_str = f"ERROR: Unknown tool '{fn_name}'"
                    else:
                        try:
                            result_str = tool_fn(state["workspace_dir"], **args)
                        except Exception as e:
                            result_str = f"ERROR: Tool '{fn_name}' raised: {e}"
            except Exception as e:
                result_str = f"ERROR: Tool '{fn_name}' raised: {e}"
        else:
            tool_fn = get_tool_fn(fn_name)
            if tool_fn is None:
                result_str = f"ERROR: Unknown tool '{fn_name}'"
            else:
                try:
                    result_str = tool_fn(state["workspace_dir"], **args)
                except Exception as e:
                    result_str = f"ERROR: Tool '{fn_name}' raised: {e}"

        logger.info(f"[Tool] {fn_name}({list(args.keys())}) -> {result_str[:200] if result_str else 'None'}")
        new_log.append(f"tool: {fn_name} (step {new_count})")

        # Check for task_complete signal
        if fn_name == "task_complete" or fn_name.endswith("__task_complete"):
            try:
                parsed = json.loads(result_str)
                if parsed.get("action") == "task_complete":
                    task_complete_triggered = True
                    summary = parsed.get("summary", "")
            except (json.JSONDecodeError, TypeError):
                pass

        new_messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result_str[:10000] if result_str else "ERROR: No result",
        })

    heartbeat_data = {
        "step": new_count,
        "max_steps": state["max_tool_calls"],
        "last_tool": tool_calls[-1]["function"]["name"] if tool_calls else "",
        "cost_usd": round(state["total_cost_usd"], 6),
        "phase": "tool_execution",
    }
    try:
        activity.heartbeat(json.dumps(heartbeat_data))
    except Exception:
        pass

    result = {
        "messages": state["messages"] + new_messages,
        "tool_call_count": new_count,
        "artifacts": new_artifacts,
        "progress_log": new_log,
    }
    if task_complete_triggered:
        result["status"] = "completed"
        result["summary"] = summary
    return result


def should_continue(state: AgenticState) -> str:
    """Conditional edge: decide whether to loop back to agent or finish."""
    # If status indicates we should stop
    if state.get("status") in ("completed", "error", "budget_exceeded", "limit_reached"):
        return "summarize"

    # Check last message for tool_calls
    last_msg = state["messages"][-1] if state["messages"] else {}
    if last_msg.get("tool_calls"):
        return "tool_executor"

    # No tool calls = final answer text
    return "summarize"


def summarize(state: AgenticState) -> AgenticState:
    """Final node: extract summary from conversation."""
    summary = state.get("summary", "")
    if not summary:
        # Use last assistant message as summary
        for msg in reversed(state["messages"]):
            if msg.get("role") == "assistant" and msg.get("content"):
                summary = msg["content"]
                break
    if not summary:
        summary = "Agent completed without producing a summary."

    status = "completed"
    if state.get("status") == "error" or state.get("error"):
        status = "failed"

    return {
        "status": status,
        "summary": summary,
        "progress_log": state["progress_log"] + [f"summarize: {status}"],
    }


# Build the Agent Graph
agent_builder = StateGraph(AgenticState)
agent_builder.add_node("plan", agent_plan)
agent_builder.add_node("agent", agent_step)
agent_builder.add_node("tool_executor", tool_executor)
agent_builder.add_node("summarize", summarize)

agent_builder.add_edge(START, "plan")
agent_builder.add_edge("plan", "agent")
agent_builder.add_conditional_edges("agent", should_continue, {
    "tool_executor": "tool_executor",
    "summarize": "summarize",
})
def should_continue_after_tools(state: AgenticState) -> str:
    """After tool execution, check if task_complete was called."""
    if state.get("status") in ("completed", "error", "budget_exceeded", "limit_reached"):
        return "summarize"
    return "agent"

agent_builder.add_conditional_edges("tool_executor", should_continue_after_tools, {
    "agent": "agent",
    "summarize": "summarize",
})
agent_builder.add_edge("summarize", END)

agent_graph = agent_builder.compile()


@track(name="run_agent_pipeline")
async def run_agent_pipeline(task_payload: dict, model_id: str) -> dict:
    """Run the agentic ReAct loop pipeline."""
    task_description = task_payload.get("description", "")
    repo_url = task_payload.get("repo_url", "")
    max_tool_calls = task_payload.get("max_tool_calls", AGENT_DEFAULTS["max_tool_calls"])
    max_cost_usd = task_payload.get("max_cost_usd", AGENT_DEFAULTS["max_cost_usd"])
    specialization = task_payload.get("specialization", "general")

    logger.info(f"[SPECIALIZATION] Task loaded with specialization: '{specialization}'")

    task_id = str(uuid.uuid4())
    workspace_dir = task_payload.get("workspace_dir") or create_workspace(task_id)

    try:
        # Build initial user message
        user_content = task_description
        if repo_url:
            user_content += f"\n\nRepository to work with: {repo_url}"

        initial_state: AgenticState = {
            "messages": [{"role": "user", "content": user_content}],
            "workspace_dir": workspace_dir,
            "tool_call_count": 0,
            "max_tool_calls": max_tool_calls,
            "max_cost_usd": max_cost_usd,
            "total_cost_usd": 0.0,
            "model_id": model_id,
            "specialization": specialization,
            "artifacts": [],
            "progress_log": [],
            "error": "",
            "status": "started",
            "summary": "",
        }

        final_state = initial_state.copy()
        start_time = time.time()

        # Recursion limit: max_tool_calls * 3 accounts for plan + agent + tool_executor per tool call, plus buffer
        recursion_limit = max(max_tool_calls * 3 + 10, 100)
        final_state = await agent_graph.ainvoke(initial_state, config={"recursion_limit": recursion_limit})

        duration = time.time() - start_time

        # Store insight to L2 if we completed successfully
        _, insights_collection = _get_knowledge_collections()
        if final_state.get("summary") and memory_store.qdrant:
            try:
                insight = f"Task: {task_description}\nResult: {final_state['summary'][:500]}"
                vector = get_embedder().embed(insight)
                entry = MemoryEntry(
                    id=str(uuid.uuid4()),
                    content=insight,
                    metadata={"task": task_description, "source": "agent", "tool_calls": final_state.get("tool_call_count", 0)},
                )
                memory_store.store_l2(insights_collection, entry, vector=vector)
                logger.info(f"[L2 Stored] Agent insight saved to Qdrant collection: {insights_collection}")
            except Exception as e:
                logger.error(f"Failed to store agent insight in Qdrant: {e}")

        # Archive to L3
        memory_store.archive_l3(task_id, {
            "task_description": task_description,
            "summary": final_state.get("summary", ""),
            "status": final_state.get("status", "unknown"),
            "total_cost_usd": final_state.get("total_cost_usd", 0.0),
            "tool_call_count": final_state.get("tool_call_count", 0),
            "progress_log": final_state.get("progress_log", []),
            "duration_seconds": duration,
        })

        artifact_files = _collect_artifacts(workspace_dir)
        
        # Get embedding model info
        embedding_model = "unknown"
        embedding_dim = 0
        try:
            emb = get_embedder()
            text_config = emb._configs.get("text")
            if text_config:
                embedding_model = text_config.model
                embedding_dim = text_config.dim
        except Exception:
            pass
        
        # Resolve actual model name from reasoning level
        actual_model = model_id
        provider = "unknown"
        try:
            # Get model from specialization config
            spec_conf = router._specializations.get(specialization, {})
            if "model" in spec_conf:
                actual_model = spec_conf["model"]
            if "provider" in spec_conf:
                provider = spec_conf["provider"]
        except Exception:
            pass

        return {
            "status": final_state.get("status", "completed"),
            "summary": final_state.get("summary", ""),
            "total_cost_usd": final_state.get("total_cost_usd", 0.0),
            "tool_call_count": final_state.get("tool_call_count", 0),
            "progress_log": final_state.get("progress_log", []),
            "duration_seconds": round(duration, 2),
            "mode": "agent",
            "artifact_files": artifact_files,
            "model_id": actual_model,
            "model_reasoning": model_id,
            "provider": provider,
            "specialization": specialization,
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
        }
    finally:
        cleanup_workspace(workspace_dir)


def _collect_artifacts(workspace_dir: str, max_size_bytes: int = 50 * 1024 * 1024) -> list[dict]:
    """Read all files written to the workspace and return them as base64-encoded dicts."""
    artifacts = []
    if not os.path.isdir(workspace_dir):
        return artifacts
    for fname in sorted(os.listdir(workspace_dir)):
        fpath = os.path.join(workspace_dir, fname)
        if not os.path.isfile(fpath):
            continue
        size = os.path.getsize(fpath)
        if size == 0 or size > max_size_bytes:
            continue
        mime_type, _ = mimetypes.guess_type(fname)
        mime_type = mime_type or "application/octet-stream"
        try:
            with open(fpath, "rb") as f:
                content_b64 = base64.b64encode(f.read()).decode()
            artifacts.append({"name": fname, "content_b64": content_b64, "mime_type": mime_type, "size_bytes": size})
        except Exception as e:
            logger.warning(f"Could not read artifact '{fname}': {e}")
    return artifacts


# ──────────────────────────────────────────────
# TASK INPUT PARSING
# ──────────────────────────────────────────────

def parse_task_input(input_task: str) -> tuple[str, dict | None]:
    """
    Detect whether input is a legacy plain string or an agent JSON payload.
    Returns: (mode, payload)
      - ("legacy", None)    for plain text tasks
      - ("agent", {...})    for JSON agent tasks
    """
    stripped = input_task.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            if payload.get("task_type") == "agent":
                return ("agent", payload)
        except json.JSONDecodeError:
            pass
    return ("legacy", None)


def detect_media_envelope(input_task: str) -> dict | None:
    """
    Detect if input is a media envelope (voice, photo, audio).
    Returns the envelope dict or None.
    """
    stripped = input_task.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            if "envelope" in payload:
                return payload["envelope"]
        except json.JSONDecodeError:
            pass
    return None


def prepare_media_context(envelope: dict, workspace_dir: str) -> tuple[str, list[str]]:
    """
    Process a media envelope and prepare context for the agent.
    Returns: (modified_task_description, tool_scope)
    """
    content_type = envelope.get("content_type", "text/plain")
    payload_b64 = envelope.get("payload")
    task_desc = envelope.get("task_description", "")
    tool_scope = envelope.get("tool_scope", [])
    metadata = envelope.get("metadata", {})
    
    if not payload_b64 or content_type == "text/plain":
        return task_desc, tool_scope
    
    os.makedirs(workspace_dir, exist_ok=True)
    
    media_bytes = base64.b64decode(payload_b64)
    extension = mimetypes.guess_extension(content_type) or ".bin"
    media_path = os.path.join(workspace_dir, f"input_media{extension}")
    
    with open(media_path, "wb") as f:
        f.write(media_bytes)
    
    logger.info(f"Saved media to {media_path} ({len(media_bytes)} bytes, {content_type})")
    
    if content_type.startswith("audio/"):
        duration = metadata.get("duration", "unknown")
        modified_desc = f"""📁 Media file available at: `{media_path}`
Type: {content_type}
Duration: {duration}s

Instructions:
1. Use the `transcribe_audio` tool with mode="fast" to transcribe the audio file
2. Then respond to the user's request: {task_desc}"""
        
        if "transcribe_audio" not in tool_scope:
            tool_scope.append("transcribe_audio")
    
    elif content_type.startswith("image/"):
        modified_desc = f"""📁 Image file available at: `{media_path}`
Type: {content_type}

Instructions:
1. Use the `analyze_image` tool to understand the image content
2. Then respond to the user's request: {task_desc}"""
        
        if "analyze_image" not in tool_scope:
            tool_scope.append("analyze_image")
    
    else:
        modified_desc = f"File available at: {media_path}\n\n{task_desc}"
    
    return modified_desc, tool_scope


# --- Temporal Activities ---

def _detect_specialization(description: str) -> str:
    """Infer specialization from plain-text task description when none is explicitly set."""
    d = description.lower()
    if any(w in d for w in ["image", "picture", "photo", "draw", "painting", "illustration", "portrait", "generate.*image", "visual"]):
        return "image_generation"
    if any(w in d for w in ["video", "animation", "film", "movie", "clip", "reel"]):
        return "video_generation"
    if any(w in d for w in ["audio", "music", "song", "sound", "speech", "podcast", "voice"]):
        return "audio_generation"
    if any(w in d for w in ["write", "article", "blog post", "slogan", "ad copy", "marketing", "copywriting"]):
        return "copywriting"
    if any(w in d for w in ["code", "implement", "function", "class", "script", "debug", "refactor", "programming"]):
        return "coding"
    if any(w in d for w in ["research", "find information", "what is", "how does", "explain", "summarize"]):
        return "research"
    return "general"


@activity.defn
async def execute_langgraph_agent(input_task: str, model_id: str, provider: str) -> dict:
    from src.execution.worker.multi_agent_graph import run_orchestrator
    
    await _ensure_tools_loaded()
    
    media_envelope = detect_media_envelope(input_task)
    
    if media_envelope:
        workspace_dir = create_workspace()
        logger.info(f"[MEDIA MODE] Detected media envelope: {media_envelope.get('content_type')}")
        
        task_description, tool_scope = prepare_media_context(media_envelope, workspace_dir)
        
        specialization = _detect_specialization(task_description)
        if "audio" in media_envelope.get("content_type", ""):
            specialization = "audio_generation"
        elif "image" in media_envelope.get("content_type", ""):
            specialization = "image_generation"
        
        payload = {
            "task_type": "agent",
            "description": task_description,
            "repo_url": "",
            "max_tool_calls": AGENT_DEFAULTS["max_tool_calls"],
            "max_cost_usd": AGENT_DEFAULTS["max_cost_usd"],
            "specialization": specialization,
            "tool_scope": tool_scope,
            "workspace_dir": workspace_dir,
        }
        
        logger.info(f"[MEDIA MODE] Prepared task with specialization={specialization}")
        return await run_orchestrator(payload, model_id)
    
    mode, payload = parse_task_input(input_task)

    if mode != "agent":
        specialization = _detect_specialization(input_task)
        logger.info(f"[AGENT MODE] Wrapping plain-text task as agent payload: {input_task[:100]} (specialization={specialization})")
        payload = {
            "task_type": "agent",
            "description": input_task,
            "repo_url": "",
            "max_tool_calls": AGENT_DEFAULTS["max_tool_calls"],
            "max_cost_usd": AGENT_DEFAULTS["max_cost_usd"],
            "specialization": specialization,
        }

    logger.info(f"[AGENT MODE] Starting Multi-Agent Orchestrator pipeline for: {payload.get('description', '')[:100]}")
    return await run_orchestrator(payload, model_id)



# --- Temporal Workflow ---

@workflow.defn
class AIOrchestrationWorkflow:
    @workflow.run
    async def run(self, task: str, model_id: str, provider: str) -> dict:
        # Use longer timeout for agent tasks
        _, payload = parse_task_input(task)
        if payload:
            timeout_minutes = AGENT_DEFAULTS["activity_timeout_minutes"]
        else:
            timeout_minutes = 10

        result = await workflow.execute_activity(
            execute_langgraph_agent,
            args=[task, model_id, provider],
            start_to_close_timeout=timedelta(minutes=timeout_minutes),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        return result

# --- Worker Runtime ---

async def main():
    # Prefer environment variables for Docker/container deployments
    temporal_host = os.environ.get("TEMPORAL_HOST_URL") or f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
    logger.info(f"Connecting to Temporal at {temporal_host}...")

    # Load plugin tools
    await _ensure_tools_loaded()

    # Initialize budget tracker
    if BUDGET_TRACKING_ENABLED and budget_tracker:
        try:
            redis_url = f"redis://{redis_cfg.get('host', 'localhost')}:{redis_cfg.get('port', 6379)}"
            db_url = os.environ.get("DATABASE_URL", "postgresql://temporal:temporal@postgres:5432/orchestrator")
            
            redis_client = redis.from_url(redis_url)
            db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
            
            budget_tracker.initialize(redis_client=redis_client, db_pool=db_pool)
            logger.info("Budget tracker initialized")
        except Exception as e:
            logger.warning(f"Could not initialize budget tracker: {e}")

    client = None
    for i in range(10):
        try:
            client = await Client.connect(temporal_host)
            logger.info(f"Successfully connected to Temporal at {temporal_host}")
            break
        except Exception as e:
            logger.warning(f"Attempt {i+1}/10 - Failed to connect to Temporal: {e}")
            await asyncio.sleep(5)

    if not client:
        logger.error("Could not connect to Temporal. Exiting.")
        return

    worker = Worker(
        client,
        task_queue="ai-orchestration-queue",
        workflows=[AIOrchestrationWorkflow, BeliefDecayWorkflow],
        activities=[execute_langgraph_agent, apply_belief_decay],
        workflow_runner=UnsandboxedWorkflowRunner()
    )
    logger.info("Worker started. Listening on 'ai-orchestration-queue'...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
