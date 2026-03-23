import operator
import json
import logging
import uuid
import time
from typing import TypedDict, Annotated, Any, List

from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send
from pydantic import BaseModel, Field

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

async def synthesis_node(state: OrchestratorState) -> dict:
    """
    Aggregates all results into a final report.
    """
    completed = state.get("completed_subtasks", {})
    summary = "Campaign / Task Results:\n"
    for tk, res in completed.items():
        summary += f"\n--- {tk.upper()} ---\n{res}\n"
        
    return {
        "status": "completed",
        "final_summary": summary,
        "progress_log": ["Synthesis complete."]
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

builder = StateGraph(OrchestratorState)
builder.add_node("planner_node", planner_node)
builder.add_node("subtask_worker", subtask_worker)
builder.add_node("synthesis_node", synthesis_node)

builder.add_edge(START, "planner_node")
builder.add_conditional_edges("planner_node", orchestrator_router, ["subtask_worker", "synthesis_node"])
builder.add_conditional_edges("subtask_worker", orchestrator_router, ["subtask_worker", "synthesis_node"])
builder.add_edge("synthesis_node", END)

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
    logger.info(f"[ORCHESTRATOR] Starting Multi-Agent Pipeline for: {task_description[:50]}...")

    initial_state = {
        "user_prompt": task_description,
        "specialization": task_payload.get("specialization", "general"),
        "execution_plan": None,
        "completed_subtasks": {},
        "shared_artifacts": {},
        "artifact_files": [],
        "progress_log": [],
        "global_cost": 0.0,
        "status": "started",
        "final_summary": "",
    }

    start_time = time.time()
    try:
        final_state = await orchestrator_graph.ainvoke(initial_state, config={"recursion_limit": 150})
    except Exception as e:
        logger.error(f"Orchestrator graph failed: {e}")
        return {"status": "error", "summary": f"Orchestrator failed: {e}"}

    duration = time.time() - start_time
    
    return {
        "status": final_state.get("status", "completed"),
        "summary": final_state.get("final_summary", ""),
        "total_cost_usd": final_state.get("global_cost", 0.0),
        "tool_call_count": len(final_state.get("completed_subtasks", {})),
        "progress_log": final_state.get("progress_log", []),
        "duration_seconds": round(duration, 2),
        "mode": "agent",
        "artifact_files": final_state.get("artifact_files", []),
    }
