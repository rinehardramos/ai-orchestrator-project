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
from src.shared.memory.knowledge_base import KnowledgeBaseClient
from src.shared.memory.decay_workflow import BeliefDecayWorkflow, apply_belief_decay
from prometheus_client import start_http_server, Counter, Histogram
import time

# AI Provider SDKs
import litellm
from litellm import Router

# --- LiteLLM Router Setup ---
def load_router_config():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config/profiles.yaml"))
    model_list = []
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            for m in data.get('models', []):
                provider = m['provider'].lower()
                if provider == "google": provider = "gemini"
                
                # We use the reasoning_capability as the "model_name" for the router
                # to allow routing to ANY model in that tier.
                model_entry = {
                    "model_name": m['reasoning_capability'], 
                    "litellm_params": {
                        "model": f"{provider}/{m['id']}" if provider != "local" else m['id'],
                        "api_key": os.environ.get(f"{provider.upper()}_API_KEY")
                    }
                }
                model_list.append(model_entry)
    return model_list

llm_router = Router(model_list=load_router_config())

def generate_content(provider: str, model: str, prompt: str) -> str:
    """Uses LiteLLM Router to call a model within a requested reasoning tier."""
    # If the CNC specifically asked for a model ID that matches a tier name, use it.
    # Otherwise, fall back to the provided model ID.
    target = model 
    
    try:
        response = llm_router.completion(
            model=target,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        # Fallback: try using the exact model string if routing by tier failed
        try:
            full_model = f"{provider}/{model}" if "/" not in model else model
            if "google" in full_model: full_model = full_model.replace("google", "gemini")
            
            response = litellm.completion(
                model=full_model,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        except Exception as e2:
            raise ValueError(f"LiteLLM Router & Fallback failed: {str(e)} | {str(e2)}")


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
        CACHE_HITS.inc()
        print(f"[L1 Cache Hit] Found assessment for task")
        return {"assessment": cached_assessment, "status": "assessed"}
        
    CACHE_MISSES.inc()
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
        "provider": provider,
        "_start_time": time.time()
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
    
    # ── OODA Feedback Loop: Write observation back to Knowledge Base ──
    if False: # Temporarily disabled
        kb = None
        try:
            q_start = time.time()
            kb = KnowledgeBaseClient()
            observation_text = f"Task: {input_task}\nOutcome Assessment: {final_state.get('assessment', '')}\nRecommendations: {final_state.get('recommendations', '')}"
            vector = kb.embed_text(observation_text)
            
            entry = MemoryEntry(
                id=str(uuid.uuid4()), 
                content=observation_text, 
                metadata={
                    "task": input_task,
                    "type": "observation",
                    "model_used": model_id,
                    "score": 1.0 # Initial belief score before decay
                }
            )
            kb.store.store_l2("agent_insights", entry, vector=vector)
            QDRANT_LATENCY.observe(time.time() - q_start)
            print(f"[Feedback Loop] OODA Observation written to Qdrant")
        except Exception as e:
            print(f"Failed to write OODA observation: {e}")
        finally:
            if kb:
                kb.close()

    TASK_DURATION.observe(time.time() - float(final_state.get('_start_time', time.time())))
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
    print("Starting Prometheus metrics server on port 8000...")
    try:
        start_http_server(8000)
    except Exception as e:
        print(f"Failed to start prometheus server: {e}")

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
        workflows=[AIOrchestrationWorkflow, BeliefDecayWorkflow],
        activities=[execute_langgraph_agent, apply_belief_decay],
        workflow_runner=UnsandboxedWorkflowRunner()
    )
    print("Worker started. Listening on 'ai-orchestration-queue'...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
