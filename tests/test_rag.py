import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
from src.orchestrator.scheduler import TaskScheduler

async def trigger_test():
    print("🚀 Triggering Test Task to check RAG on both nodes...")
    scheduler = TaskScheduler(queue_url="dummy-temporal-queue", table_name="dummy")
    
    # This description is crafted to semantically match the "Python Virtual Environments" and "Container Dependencies" issues
    task_description = "Verify IaC Demo: Missing binaries terraform pulumi and ModuleNotFoundError for boto3"
    task_id = await scheduler.submit_task(task_description)
    
    status = await scheduler.wait_for_completion(task_id, timeout=300)
    print(f"\n🏁 Final Task Status: {status}")

if __name__ == "__main__":
    asyncio.run(trigger_test())