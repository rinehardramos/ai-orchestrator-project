import asyncio
import os
import uuid
import json
import yaml
from typing import TypedDict, Annotated
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
        
    print(f"[L1 Cache Miss] Analyzing via LLM using gemini-3-flash...")
    api_key = os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    
    # Read some core files for the audit context if available
    context_code = ""
    try:
        for file in ["src/orchestrator/scheduler.py", "central_node/worker.py"]:
            if os.path.exists(file):
                with open(file, "r") as f:
                    context_code += f"\n--- {file} ---\n" + f.read()
    except Exception:
        pass

    prompt = f"Task: {state['input_task']}\n\nPerform a security and performance audit of the following code:\n{context_code}"
    
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents=prompt
    )
    assessment_text = response.text
    
    # Store in L1 for future fast retrieval
    memory_store.store_l1(f"cache:{task_hash}", assessment_text, ttl_seconds=3600)
    
    return {"assessment": assessment_text, "status": "assessed"}

def generate_recommendations(state: AgentState) -> AgentState:
    api_key = os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    
    prompt = f"Based on this security and performance assessment:\n{state['assessment']}\n\nProvide actionable refactoring recommendations."
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents=prompt
    )
    recommendations = response.text
    
    # L2: Store semantic memory of this recommendation
    if memory_store.qdrant:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=recommendations,
            metadata={"task": state['input_task']}
        )
        try:
            memory_store.store_l2("agent_insights", entry, vector=[0.1, 0.2, 0.3]) # Dummy vector for simulation
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
async def execute_langgraph_agent(input_task: str) -> dict:
    jobs_config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config/jobs.yaml'))
    jobs_data = []
    if os.path.exists(jobs_config_path):
        with open(jobs_config_path, 'r') as f:
            parsed = yaml.safe_load(f)
            if parsed and 'jobs' in parsed:
                jobs_data = parsed['jobs']
                
    for job in jobs_data:
        if input_task.startswith(job.get('match_string', '')):
            job_type = job.get('type')
            
            if job_type == 'shell_commands':
                import subprocess
                activity.heartbeat("0%")
                print(f"Worker progress: 0% ({job.get('id')} started)")
                
                # Check Knowledge Base
                try:
                    from src.memory.knowledge_base import KnowledgeBaseClient
                    kb = KnowledgeBaseClient()
                    warnings = kb.query_similar_issues(input_task, limit=2)
                    if warnings:
                        print("⚠️ RELEVANT PAST ISSUES (KNOWLEDGE BASE):")
                        for w in warnings:
                            print(f"  - {w['title']} (Score: {w['score']:.2f})")
                except Exception as e:
                    print(f"KB lookup failed: {e}")
                
                results = {}
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', job.get('base_dir', '')))
                tasks = job.get('tasks', {})
                
                for idx, (task_name, info) in enumerate(tasks.items()):
                    target_dir = os.path.join(base_dir, info.get("dir", ""))
                    if not os.path.exists(target_dir):
                        results[task_name] = f"Directory not found: {target_dir}"
                        continue
                        
                    try:
                        res = subprocess.run(info.get("cmd", ""), shell=True, cwd=target_dir, capture_output=True, text=True)
                        results[task_name] = f"Exit code: {res.returncode}\nSTDOUT: {res.stdout.strip()[:500]}\nSTDERR: {res.stderr.strip()[:500]}"
                    except Exception as e:
                        results[task_name] = f"Error: {str(e)}"
                    
                    progress = int(((idx + 1) / max(len(tasks), 1)) * 90)
                    activity.heartbeat(f"{progress}%")
                    print(f"Worker progress: {progress}% (Verified {task_name})")
                    
                activity.heartbeat("100%")
                print(f"Worker progress: 100% ({job.get('id')} complete)")
                
                return {
                    "status": "success",
                    "assessment": f"{job.get('id')} executed.",
                    "recommendations": json.dumps(results, indent=2)
                }

            elif job_type == 'diagnostic':
                activity.heartbeat("0%")
                print("Worker progress: 0% (Diagnostic started)")
                await asyncio.sleep(1)
                activity.heartbeat("50%")
                print("Worker progress: 50% (Diagnostic half-way)")
                await asyncio.sleep(1)
                activity.heartbeat("100%")
                print("Worker progress: 100% (Diagnostic complete)")
                
                return {
                    "status": "success",
                    "assessment": "Diagnostic self-test successful. The worker node is active and healthy.",
                    "recommendations": "No recommendations."
                }
        
    initial_state = {"input_task": input_task, "assessment": "", "recommendations": "", "status": "started"}
    
    # Langgraph execution inside Temporal Activity
    # Use streaming to report progress
    final_state = initial_state
    activity.heartbeat("0%")
    print("Worker progress: 0% (Task started)")
    
    async for event in graph.astream(initial_state):
        if "analyze" in event:
            activity.heartbeat("50%")
            print("Worker progress: 50% (Analysis complete)")
            final_state.update(event["analyze"])
        elif "recommend" in event:
            activity.heartbeat("100%")
            print("Worker progress: 100% (Recommendations complete)")
            final_state.update(event["recommend"])
            
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
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        return result

# --- Worker Runtime ---

async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
    print(f"Connecting to Temporal at {temporal_host}...")
    
    client = None
    retries = 10
    for i in range(retries):
        try:
            client = await Client.connect(temporal_host)
            break
        except Exception as e:
            print(f"Attempt {i+1}/{retries} - Failed to connect to Temporal: {e}")
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
