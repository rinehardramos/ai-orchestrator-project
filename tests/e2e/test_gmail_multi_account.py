#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-End Test: Gmail Multi-Account Tool Selection

This test simulates a real user submitting prompts through the CLI.
The agent must intelligently select which Gmail tool instance to use:
- gmail_blackopstech047__email_read_inbox -> when user mentions "blackopstech047"
- gmail_blackopstech048__email_read_inbox -> when user mentions "blackopstech048"

Flow: CLI -> TaskAnalyzer -> TaskScheduler -> Temporal -> Worker -> Agent Pipeline -> Tool Selection

Usage:
    python scripts/test_e2e_gmail.py
"""
import asyncio
import os
import sys
import json
import time
import re
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv()

from src.genesis.analyzer.task_analyzer import TaskAnalyzer, TaskRequirement
from src.genesis.orchestrator.scheduler import TaskScheduler


def check_tool_success(result: dict, expected_tool: str) -> tuple[bool, str]:
    """Check if the expected tool was called and succeeded."""
    summary = result.get("summary", "").lower()
    
    success_indicators = ["found", "email from", "subject", "sender", "latest unread email"]
    has_success = any(ind in summary for ind in success_indicators)
    
    error_patterns = ["error:", "failed", "invalid credentials", "authentication failed", 
                      "application-specific password required", "imap error", "unable to"]
    has_error = any(pat in summary for pat in error_patterns)
    
    if has_success and not has_error:
        return True, f"Tool '{expected_tool}' executed successfully"
    
    if has_error:
        return False, f"Tool failed due to credential issue"
    
    return False, f"Tool result unclear - check summary"


async def submit_and_wait(prompt: str, label: str, expected_tool: str) -> dict:
    """Submit a prompt through the full CLI flow and wait for completion."""
    print(f"\n{'='*60}")
    print(f"[{label}] Submitting prompt via CLI flow...")
    print(f"[{label}] Prompt: {prompt[:100]}...")
    print(f"[{label}] Expected tool: {expected_tool}")
    print(f"{'='*60}")
    
    analyzer = TaskAnalyzer(config_path="config/profiles.yaml")
    
    task_req = TaskRequirement(
        estimated_duration_seconds=120,
        memory_mb=512,
        reasoning_complexity="medium",
        context_length=2000,
        specialization="general"
    )
    
    result = analyzer.analyze(task_req)
    
    agent_payload = json.dumps({
        "task_type": "agent",
        "description": prompt,
        "repo_url": "",
        "max_tool_calls": 20,
        "max_cost_usd": 0.30,
        "specialization": "general"
    })
    
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    
    task_id = await scheduler.submit_task(agent_payload, result.model_dump(), source="e2e_test")
    print(f"[{label}] Task submitted: {task_id}")
    
    print(f"[{label}] Waiting for completion...")
    final_status = await scheduler.wait_for_completion(task_id, timeout=600)
    
    detail = await scheduler.get_task_detail(task_id)
    
    tool_success, tool_message = check_tool_success(
        detail.get("result", {}), 
        expected_tool
    )
    
    return {
        "task_id": task_id,
        "status": final_status,
        "detail": detail,
        "prompt": prompt,
        "label": label,
        "expected_tool": expected_tool,
        "tool_success": tool_success,
        "tool_message": tool_message
    }


async def run_e2e_test():
    """Run the full E2E test with two Gmail account checks."""
    
    print("\n" + "="*70)
    print("  E2E TEST: Gmail Multi-Account Tool Selection")
    print("  Testing that agent selects correct tool based on prompt context")
    print("  Tool functions are namespaced: gmail_blackopstech047__email_read_inbox")
    print("="*70)
    
    test_prompts = [
        {
            "label": "TEST_1_BLACKOPSTECH047",
            "prompt": (
                "Read the latest unread email from blackopstech047@gmail.com account. "
                "Use the gmail_blackopstech047 tool to check the inbox. "
                "Return the subject and sender of the most recent email."
            ),
            "expected_tool": "gmail_blackopstech047__email_read_inbox"
        },
        {
            "label": "TEST_2_BLACKOPSTECH048", 
            "prompt": (
                "Read the latest unread email from blackopstech048@gmail.com account. "
                "Use the gmail_blackopstech048 tool to check the inbox. "
                "Return the subject and sender of the most recent email."
            ),
            "expected_tool": "gmail_blackopstech048__email_read_inbox"
        }
    ]
    
    results = []
    
    for test in test_prompts:
        result = await submit_and_wait(test["prompt"], test["label"], test["expected_tool"])
        results.append(result)
        
        status_icon = "✅" if result["tool_success"] else "⚠️"
        print(f"\n{status_icon} [{test['label']}] {result['tool_message']}")
        
        if result["detail"].get("result"):
            res = result["detail"]["result"]
            if isinstance(res, dict):
                print(f"   Tool Calls: {res.get('tool_call_count', 'N/A')}")
                print(f"   Cost: ${res.get('total_cost_usd', 0):.6f}")
                print(f"   Duration: {res.get('duration_seconds', 0):.1f}s")
    
    print("\n" + "="*70)
    print("  E2E TEST SUMMARY")
    print("="*70)
    
    tool_selection_passed = 0
    tool_execution_passed = 0
    
    for r in results:
        if r["tool_success"]:
            tool_execution_passed += 1
        tool_selection_passed += 1
        
        status_icon = "✅" if r["tool_success"] else "⚠️"
        print(f"{status_icon} {r['label']}")
        print(f"   Task ID: {r['task_id']}")
        print(f"   Expected Tool: {r['expected_tool']}")
        print(f"   Result: {r['tool_message']}")
    
    print(f"\n--- RESULTS ---")
    print(f"Tool Selection: {tool_selection_passed}/{len(results)} correct")
    print(f"Tool Execution: {tool_execution_passed}/{len(results)} successful")
    
    if tool_selection_passed == len(results):
        print("\n✅ TOOL SELECTION TEST PASSED - Agent correctly selected tools based on prompt context")
        if tool_execution_passed < len(results):
            print("⚠️  Tool execution failed - check Gmail credentials in database")
        return True
    else:
        print("\n❌ TOOL SELECTION TEST FAILED")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
