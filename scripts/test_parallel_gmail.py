#!/usr/bin/env python3
"""
Test parallel Gmail reading from two different gmail tools.
"""

import asyncio
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.genesis.orchestrator.scheduler import TaskScheduler


async def submit_gmail_task(scheduler: TaskScheduler, tool_name: str):
    """Submit a single gmail read task."""
    task_description = json.dumps({
        "task_type": "agent",
        "description": f"Use the {tool_name} tool to read my inbox. Use email_read_inbox with limit=3, unread_only=false. List the sender, subject, and date for each email.",
        "repo_url": "",
        "max_tool_calls": 5,
        "max_cost_usd": 0.10,
        "specialization": "general"
    })
    
    analysis_result = {
        "llm_model_id": "low",
        "model_details": {"provider": "google"}
    }
    
    task_id = await scheduler.submit_task(
        task_description,
        analysis_result,
        source="cli"
    )
    
    return task_id, tool_name


async def wait_for_task(scheduler: TaskScheduler, task_id: str, tool_name: str):
    """Wait for a single task to complete."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for {tool_name} ({task_id[:8]}...)...")
    
    final_status = await scheduler.wait_for_completion(task_id, timeout=120)
    
    detail = await scheduler.get_task_detail(task_id)
    summary = ""
    if detail.get("result"):
        result = detail["result"]
        if isinstance(result, dict):
            summary = result.get("summary", "No summary")
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {tool_name} complete: {final_status}")
    return tool_name, summary


async def main():
    print("=" * 70)
    print("Parallel Gmail Read Test")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    
    # Check connectivity
    print("\n1. Checking connectivity...")
    conn = await scheduler.check_connectivity()
    for service, status in conn.items():
        icon = "✅" if status else "❌"
        print(f"   {icon} {service}")
    
    # Submit both tasks in parallel
    print("\n2. Submitting parallel tasks...")
    
    task1 = asyncio.create_task(submit_gmail_task(scheduler, "gmail_blackopstech047"))
    task2 = asyncio.create_task(submit_gmail_task(scheduler, "gmail_blackopstech048"))
    
    results = await asyncio.gather(task1, task2)
    
    task_ids = {tool_name: task_id for task_id, tool_name in results}
    
    print(f"\n   Submitted:")
    for tool_name, task_id in task_ids.items():
        print(f"   - {tool_name}: {task_id[:8]}...")
    
    # Wait for both in parallel
    print("\n3. Waiting for results (parallel execution)...")
    
    wait_tasks = [
        asyncio.create_task(wait_for_task(scheduler, task_ids["gmail_blackopstech047"], "gmail_blackopstech047")),
        asyncio.create_task(wait_for_task(scheduler, task_ids["gmail_blackopstech048"], "gmail_blackopstech048"))
    ]
    
    results = await asyncio.gather(*wait_tasks)
    
    # Print results
    print("\n" + "=" * 70)
    print("Results")
    print("=" * 70)
    
    for tool_name, summary in results:
        print(f"\n--- {tool_name} ---")
        print(summary[:1000] if summary else "No summary")
    
    print("\n" + "=" * 70)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())