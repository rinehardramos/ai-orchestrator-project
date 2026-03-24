import asyncio
import uuid
from temporalio.client import Client
from src.execution.worker.worker import AIOrchestrationWorkflow

async def main():
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    
    task_description = "Launch a marketing campaign for a new eco-friendly water bottle. It should include market research, visual branding, and a promotional video."
    
    print("Connected to Temporal. Submitting multi-agent task...")
    
    # Start the workflow
    workflow_id = f"multi-agent-campaign-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        AIOrchestrationWorkflow.run,
        args=[task_description, "google/gemini-2.0-flash-001", "openrouter"],
        id=workflow_id,
        task_queue="ai-orchestration-queue",
    )
    
    print(f"Workflow started with ID: {workflow_id}")
    
    try:
        # Wait for result
        result = await handle.result()
        print("\n=== FINAL CAMPAIGN SUMMARY ===")
        print(result.get("summary", "No summary produced."))
        print(f"\nTotal Cost: ${result.get('total_cost_usd', 0):.4f}")
        print(f"Duration: {result.get('duration_seconds', 0)}s")
    except Exception as e:
        print(f"Task Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
