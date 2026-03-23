import asyncio
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

from src.execution.worker.model_router import ModelRouter, TaskType
from src.execution.worker.embeddings import get_embedder

# opik tracing moved to top

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Worker")

# --- Global Config & Memory Store ---
config = load_settings()
temp_cfg = config.get("temporal", {})
qdrant_cfg = config.get("qdrant", {})
redis_cfg = config.get("redis", {})

# Initialize memory store with config
memory_store = HybridMemoryStore(
    redis_url=f"redis://{redis_cfg.get('host', 'localhost')}:{redis_cfg.get('port', 6379)}",
    qdrant_url=f"http://{qdrant_cfg.get('host', 'localhost')}:{qdrant_cfg.get('port', 6333)}"
)

# --- Agent Defaults (from jobs.yaml) ---
def load_agent_defaults() -> dict:
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config/jobs.yaml"))
    defaults = {"max_tool_calls": 50, "max_cost_usd": 0.50, "shell_timeout_seconds": 120, "activity_timeout_minutes": 30}
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f)
                if data and "agent_defaults" in data:
                    defaults.update(data["agent_defaults"])
    except Exception:
        pass
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
    specialization: str
    artifacts: list[str]
    progress_log: list[str]
    error: str
    status: str
    summary: str


def _fetch_qdrant_context(task_description: str) -> str:
    """Retrieve relevant past insights from Qdrant for the agent system prompt."""
    try:
        vector = get_embedder().embed(task_description)
        results = memory_store.query_l2("agent_insights_v4", vector, limit=3)
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
    )
    # Prepend system message
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    return {"messages": messages, "progress_log": ["plan: system prompt built"]}


@track(name="agent_step")
def agent_step(state: AgenticState) -> AgenticState:
    """Core agent node: call LLM, get response (may include tool_calls or final text)."""
    # Budget check
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

        tool_fn = get_tool_fn(fn_name)
        if tool_fn is None:
            result_str = f"ERROR: Unknown tool '{fn_name}'"
        else:
            try:
                # All tool fns take workspace_dir as first arg
                result_str = tool_fn(state["workspace_dir"], **args)
            except Exception as e:
                result_str = f"ERROR: Tool '{fn_name}' raised: {e}"

        logger.info(f"[Tool] {fn_name}({list(args.keys())}) -> {result_str[:200]}")
        new_log.append(f"tool: {fn_name} (step {new_count})")

        # Check for task_complete signal
        if fn_name == "task_complete":
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
            "content": result_str[:10000],  # Truncate tool output
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
    workspace_dir = create_workspace(task_id)

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
        if final_state.get("summary") and memory_store.qdrant:
            try:
                insight = f"Task: {task_description}\nResult: {final_state['summary'][:500]}"
                vector = get_embedder().embed(insight)
                entry = MemoryEntry(
                    id=str(uuid.uuid4()),
                    content=insight,
                    metadata={"task": task_description, "source": "agent", "tool_calls": final_state.get("tool_call_count", 0)},
                )
                memory_store.store_l2("agent_insights_v4", entry, vector=vector)
                logger.info("[L2 Stored] Agent insight saved to Qdrant")
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

        return {
            "status": final_state.get("status", "completed"),
            "summary": final_state.get("summary", ""),
            "total_cost_usd": final_state.get("total_cost_usd", 0.0),
            "tool_call_count": final_state.get("tool_call_count", 0),
            "progress_log": final_state.get("progress_log", []),
            "duration_seconds": round(duration, 2),
            "mode": "agent",
        }
    finally:
        cleanup_workspace(workspace_dir)


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


# --- Temporal Activities ---

@activity.defn
async def execute_langgraph_agent(input_task: str, model_id: str, provider: str) -> dict:
    from src.execution.worker.multi_agent_graph import run_orchestrator
    mode, payload = parse_task_input(input_task)

    if mode != "agent":
        # Wrap plain-text tasks as agent payloads
        logger.info(f"[AGENT MODE] Wrapping plain-text task as agent payload: {input_task[:100]}")
        payload = {
            "task_type": "agent",
            "description": input_task,
            "repo_url": "",
            "max_tool_calls": AGENT_DEFAULTS["max_tool_calls"],
            "max_cost_usd": AGENT_DEFAULTS["max_cost_usd"],
            "specialization": "general"
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
    temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
    logger.info(f"Connecting to Temporal at {temporal_host}...")

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
