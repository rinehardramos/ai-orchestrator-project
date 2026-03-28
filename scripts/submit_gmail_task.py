#!/usr/bin/env python3
"""
Submit a task to read Gmail inbox via the worker agent.

Usage:
    python scripts/submit_gmail_task.py
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.control.orchestrator.scheduler import TaskScheduler


async def main():
    print("=" * 60)
    print("Submitting Gmail Task to Worker")
    print("=" * 60)
    
    # Create scheduler
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    
    # Check connectivity
    print("\n1. Checking connectivity...")
    conn = await scheduler.check_connectivity()
    for service, status in conn.items():
        icon = "✅" if status else "❌"
        print(f"   {icon} {service}: {'reachable' if status else 'offline'}")
    
    # Create task payload - this will be executed by the worker
    task_description = json.dumps({
        "task_type": "agent",
        "description": "Use the gmail tool to read my inbox and summarize the 3 most recent emails. Use email_read_inbox with limit=3, then provide a brief summary of each email including sender, subject, and a one-line preview of the content.",
        "repo_url": "",
        "max_tool_calls": 10,
        "max_cost_usd": 0.10,
        "specialization": "general"
    })
    
    # Analysis result for routing
    analysis_result = {
        "llm_model_id": "low",
        "model_details": {
            "provider": "google"
        }
    }
    
    print("\n2. Submitting task to Temporal...")
    print(f"   Description: Read Gmail inbox and summarize emails")
    
    try:
        task_id = await scheduler.submit_task(
            task_description,
            analysis_result,
            source="cli"
        )
        
        print(f"\n✅ Task submitted successfully!")
        print(f"   Task ID: {task_id}")
        print(f"\n3. Waiting for completion...")
        
        # Wait for the task to complete
        final_status = await scheduler.wait_for_completion(task_id, timeout=300)
        
        print(f"\n{'=' * 60}")
        print(f"Task Complete: {final_status}")
        print(f"{'=' * 60}")
        
        # Get the result
        detail = await scheduler.get_task_detail(task_id)
        if detail.get("result"):
            result = detail["result"]
            if isinstance(result, dict):
                if result.get("summary"):
                    print(f"\n📋 Summary:\n{result['summary']}")
                if result.get("total_cost_usd"):
                    print(f"\n💰 Cost: ${result['total_cost_usd']:.6f}")
                if result.get("tool_call_count"):
                    print(f"🔧 Tool calls: {result['tool_call_count']}")
        
        return task_id
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(main())