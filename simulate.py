import asyncio
import os
from temporalio.client import Client

async def run_simulation():
    task = "assess the improvements on the current ai orchestration and worker system..."
    
    print("🚀 [GENESIS L0] Sending task to Central Node Temporal Cluster...")
    temporal_host = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
    
    try:
        client = await Client.connect(temporal_host)
        
        result = await client.execute_workflow(
            "AIOrchestrationWorkflow",
            task,
            id="simulated-task-1",
            task_queue="ai-orchestration-queue"
        )
        
        print("\n✅ [CENTRAL NODE] Worker Execution Complete.")
        if isinstance(result, dict):
            print("\n--- Assessment ---")
            print(result.get("assessment", "No assessment provided."))
            print("\n--- Recommendations ---")
            print(result.get("recommendations", "No recommendations provided."))
        else:
            print(f"Result: {result}")
            
    except Exception as e:
        print(f"❌ Failed to run simulation via Temporal: {e}")
        print("Please ensure the Temporal server and ai-worker in docker-compose are running.")

if __name__ == "__main__":
    asyncio.run(run_simulation())
