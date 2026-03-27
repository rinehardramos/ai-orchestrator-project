from __future__ import annotations

import operator
import json
import logging
import os
import uuid
import time
from typing import TypedDict, Annotated, Any, List

from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send
from pydantic import BaseModel, Field
from temporalio import activity

from src.execution.worker.model_router import ModelRouter, TaskType
from src.execution.worker.tools import get_tool_schemas
from src.execution.worker.worker import run_agent_pipeline  # Reuse the existing single-agent pipeline for sub-tasks

logger = logging.getLogger("MultiAgentGraph")
router = ModelRouter()

# ──────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────

class SubTaskDef(BaseModel):
    id: str = Field(description="Unique identifier for this sub-task, e.g., 'research_node'")
    description: str = Field(description="Detailed instructions of what this specific agent needs to do.")
    specialization: str = Field(description="The required specialization (e.g., 'research', 'image_generation', 'copywriting').")
    dependencies: List[str] = Field(description="List of SubTask IDs that must complete before this one starts.", default_factory=list)

class ExecutionPlan(BaseModel):
    strategy: str = Field(description="'single_agent', 'parallel_isolated', or 'coordinated_team'")
    subtasks: List[SubTaskDef] = Field(description="List of sub-tasks if strategy is not single_agent.", default_factory=list)

# ──────────────────────────────────────────────
# LANGGRAPH STATE
# ──────────────────────────────────────────────

def merge_dict(a: dict, b: dict) -> dict:
    """Reducer for merging dictionaries in LangGraph state."""
    c = a.copy()
    c.update(b)
    return c

def append_list(a: list, b: list) -> list:
    """Reducer for appending to lists in LangGraph state."""
    return a + b if a and b else (a or b or [])

class OrchestratorState(TypedDict):
    user_prompt: str
    specialization: str                                         # Passed through for single_agent tasks
    execution_plan: ExecutionPlan | None
    completed_subtasks: Annotated[dict[str, str], merge_dict]  # SubTask ID -> Result Summary
    shared_artifacts: Annotated[dict[str, str], merge_dict]    # Artifact Name -> Content
    artifact_files: Annotated[list, append_list]               # Files produced by workers
    progress_log: Annotated[list[str], append_list]
    global_cost: float
    status: str
    final_summary: str
    recovery_attempted: bool   # True after a recovery cycle — prevents infinite loops

# ──────────────────────────────────────────────
# NODES
# ──────────────────────────────────────────────

async def planner_node(state: OrchestratorState) -> dict:
    """
    The Architect LLM Node. Evaluates the user prompt and generates an ExecutionPlan.
    """
    prompt = f"""
    You are the Lead Architect for an AI Orchestration system.
    Analyze the following user request and select the most efficient ExecutionPlan.

    User Request: "{state['user_prompt']}"

    ## Strategy Selection Rules (choose the SIMPLEST that fits):

    **single_agent** — Use this by default for any task a single agent can complete in one session.
    This includes tasks that involve multiple steps, reading, writing files, saving results, or doing
    research and then writing. A single agent handles all of that naturally.
    Examples: "Tell me a joke", "Write a haiku and save it", "Find a fact about the Moon and save it to a file",
    "Generate an image of a duck", "Write code that sorts a list".

    **parallel_isolated** — Use ONLY when the request explicitly asks for multiple INDEPENDENT outputs
    that can be produced simultaneously with no shared context between them.
    Examples: "Generate an image of a cat AND write a poem about dogs (these are unrelated)",
    "Write summaries of three different articles at the same time".

    **coordinated_team** — Use ONLY when the task genuinely requires different specialized agents
    and the output of one agent is a required INPUT for the next agent to do its job.
    Examples: "Research the market for EVs, then write an investor report based on that research",
    "Generate a logo image, then write ad copy that references the specific logo design".

    ## Key Rule:
    If a task can be done by one agent (even if it has multiple steps), use single_agent.
    Do NOT split into multiple agents just because a task has two steps like "find X and save it."

    Available Specializations: "general", "coding", "research", "image_generation", "video_generation", "audio_generation", "copywriting", "quality_control".
    """
    
    try:
        response_msg, cost = router.call_llm(
            messages=[
                {"role": "system", "content": "You MUST respond ONLY with valid JSON matching the ExecutionPlan schema: {\"strategy\": \"str\", \"subtasks\": [{\"id\":\"str\", \"description\":\"str\", \"specialization\":\"str\", \"dependencies\":[]}]}"},
                {"role": "user", "content": prompt}
            ],
            task_type=TaskType.PLANNING,
            tools=[]
        )
        
        content = response_msg.content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        plan_data = json.loads(content)
        plan = ExecutionPlan(**plan_data)
        
        return {
            "execution_plan": plan,
            "progress_log": [f"Planner selected strategy: {plan.strategy} with {len(plan.subtasks)} subtasks (Cost: ${cost:.5f})"],
            "global_cost": cost
        }
    except Exception as e:
        logger.error(f"Planner failed: {e}")
        return {"status": "error", "final_summary": f"Planner failed to decompose task: {e}"}

async def subtask_worker(state: dict) -> dict:
    """
    Executes a single subtask by invoking the existing single-agent pipeline logic.
    """
    task_id = state["subtask_id"]
    specialization = state["specialization"]
    description = state["description"]
    
    logger.info(f"🚀 Spawning SubTask Worker: {task_id} [{specialization}]")
    
    payload = {
        "description": description,
        "specialization": specialization,
        "max_tool_calls": 20, 
        "max_cost_usd": 0.50
    }
    
    result = await run_agent_pipeline(payload, "google/gemini-2.0-flash-001")
    result_summary = result.get("summary", f"Completed {task_id}.")

    return {
        "completed_subtasks": {task_id: result_summary},
        "shared_artifacts": {task_id: result_summary},
        "artifact_files": result.get("artifact_files", []),
        "progress_log": [f"Worker '{task_id}' finished (Cost: ${result.get('total_cost_usd', 0):.4f}). Summary: {result_summary[:100]}..."]
    }

# Patterns that indicate a tool stub or missing capability
_TOOL_FAILURE_PATTERNS = [
    "feature pending",
    "not supported by available tools",
    "tool not available",
    "not implemented",
    "stub",
    "pending integration",
    "gif generation is not supported",
]


async def synthesis_node(state: OrchestratorState) -> dict:
    """
    Aggregates all results into a final report.
    Detects tool-capability failures and flags for self-healing recovery when possible.
    """
    completed = state.get("completed_subtasks", {})
    summary = "Campaign / Task Results:\n"
    for tk, res in completed.items():
        summary += f"\n--- {tk.upper()} ---\n{res}\n"

    # Detect tool failures
    summary_lower = summary.lower()
    has_tool_failure = any(pat in summary_lower for pat in _TOOL_FAILURE_PATTERNS)

    if has_tool_failure:
        if not state.get("recovery_attempted"):
            logger.info("[SYNTHESIS] Tool capability failure detected — flagging for self-healing recovery")
            return {
                "status": "needs_recovery",
                "final_summary": summary,
                "progress_log": ["Synthesis: tool failure detected — initiating recovery"],
            }
        else:
            # Recovery was already attempted and the retry still failed — exit the loop
            logger.warning("[SYNTHESIS] Tool failure persists after recovery attempt — aborting to prevent loop")
            return {
                "status": "failed",
                "final_summary": (
                    "[RECOVERY EXHAUSTED] Self-healing was attempted but the task still failed.\n"
                    "The implemented tool did not resolve the capability gap.\n\n"
                    f"Last result:\n{summary}"
                ),
                "progress_log": ["Synthesis: tool failure persists after recovery — loop exit"],
            }

    return {
        "status": "completed",
        "final_summary": summary,
        "progress_log": ["Synthesis complete."],
    }


async def recovery_node(state: OrchestratorState) -> dict:
    """
    Self-healing node.  When synthesis detects a missing-tool failure:
      1. Spawns a coder agent that analyzes the failure, installs any packages
         it needs via shell_exec, writes and tests the solution, then outputs
         new_tool.py + tool_schema.json.
      2. Scans the generated code for missing imports and installs them.
      3. exec()s the code and registers the tool via register_dynamic_tool().
      4. Retries the original task — the agent now has the new tool available.

    Runs at most once per task (recovery_attempted flag prevents loops).
    """
    import base64
    import re
    import sys
    import subprocess as _sp
    from src.execution.worker.worker import run_agent_pipeline
    from src.execution.worker.tools import TOOL_REGISTRY, _DYNAMIC_REGISTRY

    failure_summary = state.get("final_summary", "")
    original_prompt = state["user_prompt"]
    specialization = state.get("specialization", "general")

    logger.info(f"[RECOVERY] Self-healing for: {original_prompt[:80]}")
    logger.info(f"[RECOVERY] Failure context: {failure_summary[:300]}")

    # Notify task source that recovery has been triggered
    try:
        activity.heartbeat(json.dumps({
            "phase": "recovery_analyzing",
            "step": 0, "max_steps": 0, "cost_usd": 0,
        }))
    except Exception:
        pass

    # ── Build existing tool catalog for coder context ─────────────────────────
    existing_tools = "\n".join(
        f"  - {t['name']}: {t['schema']['function']['description']}"
        for t in TOOL_REGISTRY
    )
    if _DYNAMIC_REGISTRY:
        for dname, dentry in _DYNAMIC_REGISTRY.items():
            desc = dentry["schema"].get("function", {}).get("description", "dynamically registered")
            existing_tools += f"\n  - {dname} (dynamic): {desc}"

    # ── Step 1: coder agent analyzes failure and builds the solution ──────────
    coder_payload = {
        "description": f"""You are a tool engineer for an autonomous AI agent framework.

## The Problem
An agent tried to complete this task:
  "{original_prompt}"

It failed because:
  "{failure_summary}"

## Already Available Tools (you can call these as building blocks)
{existing_tools}

## Your Goal
Analyze the failure, determine what capability is missing, and implement it.
You have FULL autonomy: install packages, call existing tools, write code, test it.

## What You Must Produce
1. `new_tool.py` — a Python function that delivers the missing capability:
   - Signature: `def <descriptive_tool_name>(workspace_dir: str, **kwargs) -> str`
   - All output files saved inside `workspace_dir`
   - Returns `"OK: <description>"` on success, `"ERROR: <reason>"` on failure
   - Include all `import` statements the function needs at the top of the file

2. `tool_schema.json` — OpenAI function-calling schema for the tool:
   {{"name": "...", "description": "...", "parameters": {{"type": "object", "properties": {{...}}}}}}

## Workflow
1. Understand exactly what the original task needed that was not available
2. Design the simplest function that delivers it
3. Use `shell_exec` to install any packages: `pip install <package> -q`
4. Write the function to `new_tool.py` and the schema to `tool_schema.json`
5. Test it: `python new_tool.py` or a small inline test via `shell_exec`
6. Fix any errors, then call `task_complete` with what you built

No stubs. No TODOs. No placeholders. Ship working code.
""",
        "specialization": "coding",
        "max_tool_calls": 30,
        "max_cost_usd": 1.00,
    }

    coder_result = await run_agent_pipeline(coder_payload, "gemini-2.5-flash")
    logger.info(f"[RECOVERY] Coder agent status: {coder_result.get('status')} | "
                f"files: {[a['name'] for a in coder_result.get('artifact_files', [])]}")

    # ── Step 2: read artifacts ────────────────────────────────────────────────
    new_tool_code = None
    raw_schema = None

    for af in coder_result.get("artifact_files", []):
        try:
            content = base64.b64decode(af["content_b64"]).decode("utf-8", errors="replace")
        except Exception:
            continue
        if af["name"] == "new_tool.py":
            new_tool_code = content
        elif af["name"] == "tool_schema.json":
            try:
                raw_schema = json.loads(content)
            except json.JSONDecodeError:
                pass

    if not new_tool_code:
        logger.error("[RECOVERY] Coder agent did not produce new_tool.py")
        return {
            "status": "failed",
            "final_summary": (
                "Self-healing failed: coder agent did not produce tool code.\n\n"
                f"Original failure:\n{failure_summary}"
            ),
            "recovery_attempted": True,
            "progress_log": ["recovery: coder agent produced no tool code — giving up"],
        }

    # ── Scan generated code for missing imports and install them ──────────────
    # Map module names that differ from their pip package name
    _PIP_NAME = {"PIL": "Pillow", "cv2": "opencv-python", "sklearn": "scikit-learn",
                 "bs4": "beautifulsoup4", "yaml": "pyyaml", "dotenv": "python-dotenv"}
    import_names = set(re.findall(r'^\s*(?:import|from)\s+(\w+)', new_tool_code, re.MULTILINE))
    stdlib = getattr(sys, "stdlib_module_names", set())  # Python 3.10+; empty set on older
    for mod_name in import_names:
        if mod_name in stdlib or mod_name in sys.modules:
            continue
        try:
            __import__(mod_name)
        except ImportError:
            pip_name = _PIP_NAME.get(mod_name, mod_name)
            logger.info(f"[RECOVERY] Installing missing dependency '{pip_name}'...")
            _sp.run(["pip", "install", pip_name, "-q"], check=True)  # nosec B603,B607

    # exec the tool code in a controlled namespace
    from src.execution.worker import tools as _tools_mod
    namespace: dict = {
        "__builtins__": __builtins__,
        "os": __import__("os"),
        "json": __import__("json"),
        "generate_image": _tools_mod.generate_image,
    }
    try:
        exec(new_tool_code, namespace)  # nosec B102 — code written by our own coder agent, not user input
    except Exception as e:
        logger.error(f"[RECOVERY] exec failed: {e}\nCode:\n{new_tool_code[:500]}")
        return {
            "status": "failed",
            "final_summary": (
                f"Self-healing failed: tool code exec error: {e}\n\n"
                f"Original failure:\n{failure_summary}"
            ),
            "recovery_attempted": True,
            "progress_log": [f"recovery: exec failed — {e}"],
        }

    # find the new callable
    skip = {"os", "json", "generate_image", "__builtins__"}
    registered_name = None
    for sym_name, obj in namespace.items():
        if callable(obj) and not sym_name.startswith("_") and sym_name not in skip:
            # Build OpenAI-format schema
            if raw_schema:
                # Agent may have written the inner "function" dict or the full wrapper
                if "type" in raw_schema and raw_schema["type"] == "function":
                    openai_schema = raw_schema
                else:
                    openai_schema = {"type": "function", "function": raw_schema}
            else:
                openai_schema = {
                    "type": "function",
                    "function": {
                        "name": sym_name,
                        "description": f"Dynamically implemented tool: {sym_name}",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
            _tools_mod.register_dynamic_tool(sym_name, obj, openai_schema)
            registered_name = sym_name
            logger.info(f"[RECOVERY] Registered new tool: '{sym_name}'")
            break

    if not registered_name:
        logger.error("[RECOVERY] No callable found in generated new_tool.py")
        return {
            "status": "failed",
            "final_summary": (
                "Self-healing failed: no callable found in generated tool code.\n\n"
                f"Original failure:\n{failure_summary}"
            ),
            "recovery_attempted": True,
            "progress_log": ["recovery: no callable in generated code — giving up"],
        }

    # ── Step 3: also persist the new tool to tools.py (survives restarts) ────
    try:
        tools_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "tools.py")
        )
        # Build the TOOL_REGISTRY entry to append
        fn_params = openai_schema.get("function", {}).get("parameters", {})
        props = fn_params.get("properties", {})
        props_repr = repr(props)
        persist_block = f'''

# ── Dynamically added by self-healing recovery ──
{new_tool_code}

TOOL_REGISTRY.append({{
    "name": "{registered_name}",
    "fn": {registered_name},
    "schema": {{
        "type": "function",
        "function": {{
            "name": "{registered_name}",
            "description": {repr(openai_schema.get("function", {{}}).get("description", registered_name))},
            "parameters": {props_repr},
        }},
    }},
}})
'''
        with open(tools_path, "a") as f:
            f.write(persist_block)
        logger.info(f"[RECOVERY] Persisted '{registered_name}' to tools.py")
    except Exception as e:
        logger.warning(f"[RECOVERY] Could not persist to tools.py (tool still active in-memory): {e}")

    # ── Step 4: retry the original task ──────────────────────────────────────
    # Notify task source that the tool was implemented and the retry is starting
    try:
        activity.heartbeat(json.dumps({
            "phase": "recovery_retry",
            "tool": registered_name,
            "step": 0, "max_steps": 0, "cost_usd": 0,
        }))
    except Exception:
        pass

    logger.info(f"[RECOVERY] Tool '{registered_name}' ready. Retrying: {original_prompt[:80]}")
    retry_payload = {
        "description": original_prompt,
        "specialization": specialization,
        "max_tool_calls": 25,
        "max_cost_usd": 0.50,
    }
    retry_result = await run_agent_pipeline(retry_payload, "gemini-2.5-flash")
    retry_status = retry_result.get("status", "completed")
    retry_summary = retry_result.get("summary", "(no summary)")

    logger.info(f"[RECOVERY] Retry status: {retry_status}")

    return {
        "status": retry_status,
        "final_summary": (
            f"[SELF-HEALED] Implemented '{registered_name}' and retried the task.\n\n"
            f"{retry_summary}"
        ),
        "artifact_files": retry_result.get("artifact_files", []),
        "recovery_attempted": True,
        "progress_log": [
            f"recovery: implemented and registered '{registered_name}'",
            f"recovery: retry completed — status={retry_status}",
        ],
    }


# ──────────────────────────────────────────────
# ROUTING LOGIC
# ──────────────────────────────────────────────

def orchestrator_router(state: OrchestratorState) -> list[Send] | str:
    """
    Decides whether to spawn more workers or synthesize results.
    """
    plan = state.get("execution_plan")
    completed = state.get("completed_subtasks", {})
    
    if state.get("status") == "error" or not plan:
        return "synthesis_node"
        
    sends = []
    
    # 1. Single Agent Strategy
    if plan.strategy == "single_agent":
        if "main_task" in completed:
            return "synthesis_node"
        return [Send("subtask_worker", {
            "subtask_id": "main_task",
            "description": state["user_prompt"],
            "specialization": state.get("specialization", "general"),
            "shared_artifacts": state.get("shared_artifacts", {})
        })]

    # 2. Parallel / Coordinated Strategy
    shared_artifacts = state.get("shared_artifacts", {})
    for task in plan.subtasks:
        if task.id not in completed:
            deps_met = all(dep in completed for dep in task.dependencies)
            if deps_met:
                upstream_context = ""
                for dep_id in task.dependencies:
                    artifact = shared_artifacts.get(dep_id, "")
                    if artifact:
                        upstream_context += f"\n\n## Output from upstream agent '{dep_id}':\n{artifact}"

                enriched_description = task.description + upstream_context

                sends.append(Send("subtask_worker", {
                    "subtask_id": task.id,
                    "description": enriched_description,
                    "specialization": task.specialization,
                    "shared_artifacts": shared_artifacts,
                }))
                
    if sends:
        return sends
        
    # 3. All completion check
    if len(completed) >= len(plan.subtasks) and plan.subtasks:
        return "synthesis_node"
        
    return "synthesis_node"

# ──────────────────────────────────────────────
# GRAPH DEFINITION
# ──────────────────────────────────────────────

def after_synthesis(state: OrchestratorState) -> str:
    """Route to recovery if a tool failure was detected, otherwise end."""
    if state.get("status") == "needs_recovery" and not state.get("recovery_attempted"):
        return "recovery_node"
    return END


builder = StateGraph(OrchestratorState)
builder.add_node("planner_node", planner_node)
builder.add_node("subtask_worker", subtask_worker)
builder.add_node("synthesis_node", synthesis_node)
builder.add_node("recovery_node", recovery_node)

builder.add_edge(START, "planner_node")
builder.add_conditional_edges("planner_node", orchestrator_router, ["subtask_worker", "synthesis_node"])
builder.add_conditional_edges("subtask_worker", orchestrator_router, ["subtask_worker", "synthesis_node"])
builder.add_conditional_edges("synthesis_node", after_synthesis, ["recovery_node", END])
builder.add_edge("recovery_node", END)

orchestrator_graph = builder.compile()

# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

try:
    from opik import track
except ImportError:
    def track(**kwargs):
        def decorator(fn): return fn
        return decorator

@track(name="run_orchestrator")
async def run_orchestrator(task_payload: dict, model_id: str) -> dict:
    """Run the multi-agent Orchestrator loop pipeline."""
    task_description = task_payload.get("description", "")
    specialization = task_payload.get("specialization", "general")
    logger.info(f"[ORCHESTRATOR] Starting Multi-Agent Pipeline for: {task_description[:50]}...")

    initial_state = {
        "user_prompt": task_description,
        "specialization": specialization,
        "execution_plan": None,
        "completed_subtasks": {},
        "shared_artifacts": {},
        "artifact_files": [],
        "progress_log": [],
        "global_cost": 0.0,
        "status": "started",
        "final_summary": "",
        "recovery_attempted": False,
    }

    start_time = time.time()
    try:
        final_state = await orchestrator_graph.ainvoke(initial_state, config={"recursion_limit": 150})
    except Exception as e:
        logger.error(f"Orchestrator graph failed: {e}")
        return {"status": "error", "summary": f"Orchestrator failed: {e}"}

    duration = time.time() - start_time
    
    # Get embedding model info
    embedding_model = "unknown"
    embedding_dim = 0
    try:
        from src.execution.worker.embeddings import get_embedder
        emb = get_embedder()
        text_config = emb._configs.get("text")
        if text_config:
            embedding_model = text_config.model
            embedding_dim = text_config.dim
    except Exception:
        pass
    
    return {
        "status": final_state.get("status", "completed"),
        "summary": final_state.get("final_summary", ""),
        "total_cost_usd": final_state.get("global_cost", 0.0),
        "tool_call_count": len(final_state.get("completed_subtasks", {})),
        "progress_log": final_state.get("progress_log", []),
        "duration_seconds": round(duration, 2),
        "mode": "agent",
        "artifact_files": final_state.get("artifact_files", []),
        "model_id": model_id,
        "specialization": specialization,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
    }
