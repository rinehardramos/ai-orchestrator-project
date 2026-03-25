"""
End-to-End Live Test — submits tasks through Temporal so the worker handles all execution.
Tests all orchestration modes: single_agent, parallel_isolated, coordinated_team, and media.

Usage:
    python -m tests.test_e2e_live
"""
import asyncio
import json
import sys
import os
import uuid
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from temporalio.client import Client, WorkflowExecutionStatus

TEMPORAL_HOST = "macbook.local:7233"
TASK_QUEUE = "ai-orchestration-queue"
TIMEOUT_MINUTES = 8
SEP = "=" * 65

TESTS = [
    {
        "label": "1. SINGLE AGENT — simple fact",
        "description": "Tell me one fun fact about the Moon. Save your answer in a file called moon_fact.txt.",
        "specialization": "general",
    },
    {
        "label": "2. PARALLEL ISOLATED — two independent haikus",
        "description": (
            "Do two completely independent things: "
            "(A) Write a haiku about the ocean and save it to ocean.txt. "
            "(B) Write a haiku about mountains and save it to mountains.txt. "
            "These tasks are independent of each other."
        ),
        "specialization": "general",
    },
    {
        "label": "3. COORDINATED TEAM — research then slogan",
        "description": (
            "First, research and write one specific interesting fact about the Python programming language. "
            "Then, based on that exact fact, write a one-sentence marketing slogan for a Python coding bootcamp. "
            "Save the final result (fact + slogan) to result.txt."
        ),
        "specialization": "general",
    },
    {
        "label": "4. IMAGE GENERATION — floating duck",
        "description": "Generate an image of a cheerful rubber duck floating on water.",
        "specialization": "image_generation",
    },
]


async def submit_and_wait(client: Client, test: dict) -> dict:
    label = test["label"]
    description = test["description"]
    specialization = test.get("specialization", "general")

    task_payload = json.dumps({
        "task_type": "agent",
        "description": description,
        "repo_url": "",
        "max_tool_calls": 20,
        "max_cost_usd": 0.50,
        "specialization": specialization,
    })

    task_id = str(uuid.uuid4())

    print(f"\n{SEP}")
    print(f"  {label}")
    print(f"  Task ID : {task_id}")
    print(f"  Prompt  : {description[:100]}...")
    print(SEP)

    handle = await client.start_workflow(
        "AIOrchestrationWorkflow",
        args=[task_payload, "gemini-2.5-flash", "google"],
        id=task_id,
        task_queue=TASK_QUEUE,
    )

    # Poll for completion with progress updates
    last_progress = None
    start = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > TIMEOUT_MINUTES * 60:
            print(f"  ⏰ TIMEOUT after {TIMEOUT_MINUTES}m")
            return {"status": "timeout", "task_id": task_id}

        desc = await handle.describe()

        if desc.status != WorkflowExecutionStatus.RUNNING:
            break

        # Heartbeat progress
        if desc.raw_description.pending_activities:
            act = desc.raw_description.pending_activities[0]
            if act.heartbeat_details:
                from temporalio.converter import default as temporal_default
                try:
                    payloads = act.heartbeat_details.payloads
                    progress = temporal_default().payload_converter.from_payloads(payloads)[0]
                    if progress != last_progress:
                        if isinstance(progress, str) and progress.startswith("{"):
                            try:
                                hb = json.loads(progress)
                                display = (
                                    f"  📈 Step {hb.get('step','?')}/{hb.get('max_steps','?')} "
                                    f"| ${hb.get('cost_usd',0):.4f} "
                                    f"| {hb.get('phase','')} "
                                    f"| {hb.get('last_tool','')}"
                                )
                                print(display)
                            except Exception:
                                print(f"  📈 {progress}")
                        last_progress = progress
                except Exception:
                    pass

        await asyncio.sleep(2)

    result = await handle.result()
    status = result.get("status", "unknown")
    cost = result.get("total_cost_usd", 0.0)
    tool_calls = result.get("tool_call_count", 0)
    duration = result.get("duration_seconds", 0)
    artifacts = result.get("artifact_files", [])
    summary = result.get("summary", "(no summary)")
    progress_log = result.get("progress_log", [])

    # Find which strategy the planner chose
    strategy_line = next((l for l in progress_log if "strategy" in l.lower()), "n/a")

    print(f"  Status   : {status}")
    print(f"  Strategy : {strategy_line}")
    print(f"  Duration : {duration:.1f}s")
    print(f"  Cost     : ${cost:.5f}")
    print(f"  Tools    : {tool_calls}")
    print(f"  Files    : {len(artifacts)}  {[a['name'] for a in artifacts]}")
    print(f"\n  Summary:\n{summary[:500]}")

    passed = status == "completed"
    print(f"\n  {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "label": label,
        "task_id": task_id,
        "status": status,
        "strategy": strategy_line,
        "duration": duration,
        "cost": cost,
        "files": [a["name"] for a in artifacts],
        "passed": passed,
    }


async def main():
    print(f"\n{'#'*65}")
    print(f"  E2E LIVE TEST — Temporal at {TEMPORAL_HOST}")
    print(f"  Testing {len(TESTS)} scenarios end-to-end")
    print(f"{'#'*65}")

    client = await Client.connect(TEMPORAL_HOST)

    results = []
    for test in TESTS:
        try:
            r = await submit_and_wait(client, test)
            results.append(r)
        except Exception as e:
            print(f"  ❌ Exception: {e}")
            results.append({"label": test["label"], "passed": False, "error": str(e)})

    # Final report
    print(f"\n{'#'*65}")
    print(f"  FINAL REPORT")
    print(f"{'#'*65}")
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    for r in results:
        icon = "✅" if r.get("passed") else "❌"
        print(f"  {icon} {r.get('label', 'unknown')}")
        if not r.get("passed") and r.get("error"):
            print(f"     Error: {r['error']}")
    print(f"\n  {passed}/{total} tests passed")
    print(f"{'#'*65}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
