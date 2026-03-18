import asyncio
import os
import sys

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from src.orchestrator.scheduler import TaskScheduler

async def trigger_verification():
    print("🚀 Triggering IaC Demo Verification on the Worker Node...")
    scheduler = TaskScheduler(queue_url="dummy-temporal-queue", table_name="dummy")
    
    task_description = "Verify IaC Demo: Check terraform, pulumi, and cdk"
    task_id = await scheduler.submit_task(task_description)
    
    print(f"✅ Task submitted to Temporal with ID: {task_id}")
    print("⏳ Waiting for the worker node to complete the verification...")
    
    status = await scheduler.wait_for_completion(task_id, timeout=300)
    print(f"\n🏁 Final Task Status: {status}")

if __name__ == "__main__":
    asyncio.run(trigger_verification())
