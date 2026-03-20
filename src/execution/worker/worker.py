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

# Prometheus
from prometheus_client import start_http_server, Counter, Histogram
import time

# Local imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
from src.shared.memory.knowledge_base import KnowledgeBaseClient
from src.shared.memory.decay_workflow import BeliefDecayWorkflow, apply_belief_decay
from src.config import load_settings

memory_store = HybridMemoryStore()

CACHE_HITS = Counter('agent_cache_hits_total', 'Total number of L1 cache hits')
CACHE_MISSES = Counter('agent_cache_misses_total', 'Total number of L1 cache misses')
QDRANT_LATENCY = Histogram('qdrant_latency_seconds', 'Latency of Qdrant vector operations')
TASK_DURATION = Histogram('agent_task_duration_seconds', 'Total duration of Langgraph agent task')
# AI Provider SDKs
import litellm
from litellm import Router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Worker")

# --- Prometheus Metrics ---
CACHE_HITS = Counter("worker_cache_hits_total", "Number of L1 cache hits")
CACHE_MISSES = Counter("worker_cache_misses_total", "Number of L1 cache misses")
TASK_DURATION = Histogram("worker_task_duration_seconds", "Time spent processing a task")
QDRANT_LATENCY = Histogram("worker_qdrant_latency_seconds", "Time spent querying Qdrant")

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

# --- LiteLLM Router Setup ---
def load_router_config():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config/profiles.yaml"))
    model_list = []
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            for m in data.get('models', []):
                provider = m['provider'].lower()
                if provider == "google": 
                    provider = "gemini"
                elif provider == "local":
                    provider = "ollama"
                
                env_key_name = f"{provider.upper()}_API_KEY"
                model_entry = {
                    "model_name": m['reasoning_capability'], 
                    "litellm_params": {
                        "model": f"{provider}/{m['id']}",
                        "api_key": os.environ.get(env_key_name, "dummy-key")
                    }
                }
                model_list.append(model_entry)
    return model_list

llm_router = Router(model_list=load_router_config())

def generate_content(provider: str, model: str, prompt: str) -> tuple[str, float]:
    """
    Uses LiteLLM Router to call a model within a requested reasoning tier.
    Returns (content, cost_usd).
    """
    target = model
    try:
        response = llm_router.completion(
            model=target,
            messages=[{"role": "user", "content": prompt}]
        )
        cost = litellm.completion_cost(completion_response=response)
        return response.choices[0].message.content, cost
    except Exception as e:
        try:
            full_model = f"{provider}/{model}" if "/" not in model else model
            if "google" in full_model:
                full_model = full_model.replace("google", "gemini")

            response = litellm.completion(
                model=full_model,
                messages=[{"role": "user", "content": prompt}]
            )
            cost = litellm.completion_cost(completion_response=response)
            return response.choices[0].message.content, cost
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
    total_cost_usd: float

def analyze_current_system(state: AgentState) -> AgentState:
    task_hash = str(hash(state['input_task']))
    cached_assessment = memory_store.get_l1(f"cache:{task_hash}")
    
    if cached_assessment:
        CACHE_HITS.inc()
        logger.info(f"[L1 Cache Hit] Found assessment for task")
        return {"assessment": cached_assessment, "status": "assessed"}
        
    CACHE_MISSES.inc()
    logger.info(f"[L1 Cache Miss] Analyzing via LLM using {state['model_id']}...")

    context_code = ""
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        for file_rel in ["src/cnc/orchestrator/scheduler.py", "src/execution/worker/worker.py"]:
            file_path = os.path.join(project_root, file_rel)
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    context_code += f"\n--- {file_rel} ---\n" + f.read()
    except Exception:
        pass

    prompt = f"Task: {state['input_task']}\n\nPerform a security and performance audit of the following code:\n{context_code}"

    assessment_text, cost = generate_content(state['provider'], state['model_id'], prompt)
    memory_store.store_l1(f"cache:{task_hash}", assessment_text, ttl_seconds=3600)

    prior_cost = state.get("total_cost_usd", 0.0)
    return {"assessment": assessment_text, "status": "assessed", "total_cost_usd": prior_cost + cost}

def generate_recommendations(state: AgentState) -> AgentState:
    prompt = f"Based on this security and performance assessment:\n{state['assessment']}\n\nProvide actionable refactoring recommendations."

    recommendations, cost = generate_content(state['provider'], state['model_id'], prompt)
    prior_cost = state.get("total_cost_usd", 0.0)
    
    if memory_store.qdrant:
        entry = MemoryEntry(id=str(uuid.uuid4()), content=recommendations, metadata={"task": state['input_task']})
        try:
            embed_response = litellm.embedding(model="gemini/gemini-embedding-001", input=[recommendations])
            vector = embed_response.data[0]["embedding"]
            memory_store.store_l2("agent_insights", entry, vector=vector)
            logger.info(f"[L2 Stored] Insight saved to Qdrant with real embedding")
        except Exception as e:
            logger.error(f"Failed to store in Qdrant: {e}")

    total_cost = prior_cost + cost
    logger.info(f"[Cost] Task total cost: ${total_cost:.6f} USD")
    return {"recommendations": recommendations, "status": "completed", "total_cost_usd": total_cost}

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
    initial_state = {
        "input_task": input_task,
        "assessment": "",
        "recommendations": "",
        "status": "started",
        "model_id": model_id,
        "provider": provider,
        "total_cost_usd": 0.0,
        "_start_time": time.time()
    }
    
    final_state = initial_state
    activity.heartbeat("0%")
    logger.info(f"Worker progress: 0% (Task started with model {model_id})")
    
    async for event in graph.astream(initial_state):
        if "analyze" in event:
            activity.heartbeat("50%")
            logger.info("Worker progress: 50% (Analysis complete)")
            final_state.update(event["analyze"])
        elif "recommend" in event:
            activity.heartbeat("100%")
            logger.info("Worker progress: 100% (Recommendations complete)")
            final_state.update(event["recommend"])
            
    task_id = str(uuid.uuid4())
    memory_store.archive_l3(task_id, final_state)
    logger.info(f"[L3 Archived] Full state archived to S3")
    
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
    logger.info("Starting Prometheus metrics server on port 8000...")
    try:
        start_http_server(8000)
    except Exception as e:
        logger.error(f"Failed to start prometheus server: {e}")

    temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
    logger.info(f"Connecting to Temporal at {temporal_host}...")
    
    client = None
    for i in range(10):
        try:
            client = await Client.connect(temporal_host)
            logger.info(f"✅ Successfully connected to Temporal at {temporal_host}")
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
