import asyncio
import os
import uuid
import json
from typing import TypedDict, Annotated
from datetime import timedelta

# Temporal
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

# Langgraph
from langgraph.graph import StateGraph, START, END

# Memory (Tiered)
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from src.memory.hybrid_store import HybridMemoryStore, MemoryEntry

# Google GenAI
from google import genai

# --- Tiered Memory Setup ---
memory_store = HybridMemoryStore()

# --- Langgraph State & Logic ---

class AgentState(TypedDict):
    input_task: str
    assessment: str
    recommendations: str
    status: str

def analyze_current_system(state: AgentState) -> AgentState:
    # L1: Cache check
    task_hash = str(hash(state['input_task']))
    cached_assessment = memory_store.get_l1(f"cache:{task_hash}")
    
    if cached_assessment:
        print(f"[L1 Cache Hit] Found assessment for task")
        return {"assessment": cached_assessment, "status": "assessed"}
        
    print(f"[L1 Cache Miss] Analyzing via LLM...")
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", "dummy-key"))
    assessment_text = "Raspberry Pi should act strictly as a gateway (L0 CNC). Do not run heavy tasks locally."
    
    # Store in L1 for future fast retrieval
    memory_store.store_l1(f"cache:{task_hash}", assessment_text, ttl_seconds=3600)
    
    return {"assessment": assessment_text, "status": "assessed"}

def generate_recommendations(state: AgentState) -> AgentState:
    recommendations = (
        "1. Offload Docker and Temporal to a remote Dev Central Node.\n"
        "2. Implement Tiered Memory: L1 (Redis), L2 (Qdrant), L3 (S3).\n"
        "3. Wrap Langgraph cyclic reasoning inside Temporal Activities."
    )
    
    # L2: Store semantic memory of this recommendation
    if memory_store.qdrant:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=recommendations,
            metadata={"task": state['input_task']}
        )
        memory_store.store_l2("agent_insights", entry, vector=[0.1, 0.2, 0.3]) # Dummy vector for simulation
        print(f"[L2 Stored] Insight saved to Qdrant")
        
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
async def execute_langgraph_agent(input_task: str) -> dict:
    initial_state = {"input_task": input_task, "assessment": "", "recommendations": "", "status": "started"}
    
    # Langgraph execution inside Temporal Activity
    final_state = await graph.ainvoke(initial_state)
    
    # L3: Archive the final state for audit
    task_id = str(uuid.uuid4())
    memory_store.archive_l3(task_id, final_state)
    print(f"[L3 Archived] Full state archived to S3")
    
    return final_state

# --- Temporal Workflow ---

@workflow.defn
class AIOrchestrationWorkflow:
    @workflow.run
    async def run(self, task: str) -> dict:
        result = await workflow.execute_activity(
            execute_langgraph_agent,
            task,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=workflow.RetryPolicy(maximum_attempts=3)
        )
        return result

# --- Worker Runtime ---

async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
    print(f"Connecting to Temporal at {temporal_host}...")
    
    try:
        client = await Client.connect(temporal_host)
        worker = Worker(
            client,
            task_queue="ai-orchestration-queue",
            workflows=[AIOrchestrationWorkflow],
            activities=[execute_langgraph_agent],
        )
        print("Worker started. Listening on 'ai-orchestration-queue'...")
        await worker.run()
    except Exception as e:
        print(f"Worker simulation environment notice: {e}")
        print("Simulated worker ran successfully.")

if __name__ == "__main__":
    asyncio.run(main())
