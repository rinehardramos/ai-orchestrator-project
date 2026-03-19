import asyncio
from src.cnc.orchestrator.scheduler import TaskScheduler

async def main():
    print("Initializing TaskScheduler...")
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    
    analysis_result = {
        "llm_model_id": "gemini-pro",
        "model_details": {"provider": "google"}
    }
    
    task_desc = "Testing Observability Task Dashboard Integration - " + str(asyncio.get_event_loop().time())
    print(f"Submitting task: {task_desc}")
    task_id = await scheduler.submit_task(task_desc, analysis_result)
    print(f"Submitted task: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
