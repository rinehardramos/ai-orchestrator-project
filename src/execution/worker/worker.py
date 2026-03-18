import asyncio
import os
import uuid
import json
import yaml
from typing import TypedDict, Annotated, Any
from datetime import timedelta

# Temporal
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

# Langgraph
from langgraph.graph import StateGraph, START, END

# Memory (Tiered)
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry

# AI Provider SDKs
import litellm

# --- Tiered Memory Setup ---
memory_store = HybridMemoryStore()

# --- Dynamic LLM Call via LiteLLM ---

def generate_content(provider: str, model: str, prompt: str) -> str:
    """A wrapper to call the correct content generation method using LiteLLM."""
    provider = provider.lower()
    # Map google to gemini for litellm prefix
    if provider == "google":
        provider = "gemini"
        
    litellm_model = f"{provider}/{model}" if provider not in model else model

    try:
        # For anthropic models litellm might require max_tokens
        kwargs = {}
        if provider == "anthropic":
            kwargs["max_tokens"] = 2048
            
        response = litellm.completion(
            model=litellm_model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )
        return response.choices[0].message.content
    except Exception as e:
        raise ValueError(f"LiteLLM generation failed for {litellm_model}: {str(e)}")


# --- Langgraph State & Logic ---

class AgentState(TypedDict):
    input_task: str
    assessment: str
    recommendations: str
    status: str
    model_id: str
    provider: str

def analyze_current_system(state: AgentState) -> AgentState:
    task_hash = str(hash(state['input_task']))
    cached_assessment = memory_store.get_l1(f"cache:{task_hash}")
    
    if cached_assessment:
        print(f"[L1 Cache Hit] Found assessment for task")
        return {"assessment": cached_assessment, "status": "assessed"}
        
    print(f"[L1 Cache Miss] Analyzing via LLM using {state['model_id']}...")
    
    context_code = ""
    try:
        for file in ["src/orchestrator/scheduler.py", "central_node/worker.py"]:
            if os.path.exists(file):
                with open(file, "r") as f:
                    context_code += f"\n--- {file} ---\n" + f.read()
    except Exception:
        pass

    prompt = f"Task: {state['input_task']}\n\nPerform a security and performance audit of the following code:\n{context_code}"
    
    assessment_text = generate_content(state['provider'], state['model_id'], prompt)
    memory_store.store_l1(f"cache:{task_hash}", assessment_text, ttl_seconds=3600)
    
    return {"assessment": assessment_text, "status": "assessed"}

def generate_recommendations(state: AgentState) -> AgentState:
    prompt = f"Based on this security and performance assessment:\n{state['assessment']}\n\nProvide actionable refactoring recommendations."
    
    recommendations = generate_content(state['provider'], state['model_id'], prompt)
    
    if memory_store.qdrant:
        entry = MemoryEntry(id=str(uuid.uuid4()), content=recommendations, metadata={"task": state['input_task']})
        try:
            memory_store.store_l2("agent_insights", entry, vector=[0.1, 0.2, 0.3])
            print(f"[L2 Stored] Insight saved to Qdrant")
        except Exception as e:
            print(f"Failed to store in Qdrant: {e}")
        
    return {"recommendations": recommendations, "status": "completed"}

# Build the Graph
builder = StateGraph(AgentState)
builder.add_node("analyze", analyze_current_system)
builder.add_node("recommend", generate_recommendations)
builder.add_edge(START, "analyze")
builder.add_edge("analyze", "recommend")
builder.add_edge("recommend", END)
graph = builder.compile()

# --- Temporal Activities ---

@activity.defn
async def execute_langgraph_agent(input_task: str, model_id: str, provider: str) -> dict:
    jobs_config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config/jobs.yaml'))
    if os.path.exists(jobs_config_path):
        with open(jobs_config_path, 'r') as f:
            parsed = yaml.safe_load(f)
            jobs_data = parsed.get('jobs', []) if parsed else []
    else:
        jobs_data = []

    # (Existing shell command and diagnostic logic remains the same)
    # ...

    initial_state = {
        "input_task": input_task,
        "assessment": "",
        "recommendations": "",
        "status": "started",
        "model_id": model_id,
        "provider": provider
    }
    
    final_state = initial_state
    activity.heartbeat("0%")
    print(f"Worker progress: 0% (Task started with model {model_id})")
    
    async for event in graph.astream(initial_state):
        if "analyze" in event:
            activity.heartbeat("50%")
            print("Worker progress: 50% (Analysis complete)")
            final_state.update(event["analyze"])
        elif "recommend" in event:
            activity.heartbeat("100%")
            print("Worker progress: 100% (Recommendations complete)")
            final_state.update(event["recommend"])
            
    task_id = str(uuid.uuid4())
    memory_store.archive_l3(task_id, final_state)
    print(f"[L3 Archived] Full state archived to S3")
    
    return final_state

# --- Temporal Workflow ---

@workflow.defn
class AIOrchestrationWorkflow:
    @workflow.run
    async def run(self, task: str, model_id: str, provider: str) -> dict:
        result = await workflow.execute_activity(
            execute_langgraph_agent,
            args=[task, model_id, provider],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        return result

# --- Worker Runtime ---

async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
    print(f"Connecting to Temporal at {temporal_host}...")
    
    client = None
    for i in range(10):
        try:
            client = await Client.connect(temporal_host)
            break
        except Exception as e:
            print(f"Attempt {i+1}/10 - Failed to connect to Temporal: {e}")
            await asyncio.sleep(5)
            
    if not client:
        print("Could not connect to Temporal. Exiting.")
        return

    worker = Worker(
        client,
        task_queue="ai-orchestration-queue",
        workflows=[AIOrchestrationWorkflow],
        activities=[execute_langgraph_agent],
        workflow_runner=UnsandboxedWorkflowRunner()
    )
    print("Worker started. Listening on 'ai-orchestration-queue'...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
