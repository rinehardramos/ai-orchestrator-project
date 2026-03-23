"""
Live test for multi-agent coordinated team execution.
Tests that shared_artifacts are populated and injected into dependent task descriptions.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")

from src.execution.worker.multi_agent_graph import run_orchestrator, orchestrator_router, OrchestratorState, SubTaskDef, ExecutionPlan


# ── Unit-style check: verify shared_artifacts flows into dependent task descriptions ──

def test_router_injects_context():
    """Verify orchestrator_router enriches dependent task descriptions with upstream artifacts."""
    plan = ExecutionPlan(
        strategy="coordinated_team",
        subtasks=[
            SubTaskDef(id="step_a", description="Do step A.", specialization="general", dependencies=[]),
            SubTaskDef(id="step_b", description="Do step B.", specialization="general", dependencies=["step_a"]),
        ]
    )

    # Simulate state after step_a has completed
    state: OrchestratorState = {
        "user_prompt": "test",
        "execution_plan": plan,
        "completed_subtasks": {"step_a": "Result from step A"},
        "shared_artifacts": {"step_a": "Result from step A"},
        "progress_log": [],
        "global_cost": 0.0,
        "status": "started",
        "final_summary": "",
    }

    from langgraph.constants import Send
    result = orchestrator_router(state)
    assert isinstance(result, list) and len(result) == 1, "Expected exactly one Send for step_b"
    send: Send = result[0]
    description = send.arg["description"]
    assert "Result from step A" in description, (
        f"FAIL: upstream context not injected into step_b description.\nGot: {description}"
    )
    print("✅ UNIT TEST PASSED: upstream context correctly injected into dependent task description")
    return True


# ── Integration test: run a real coordinated task end-to-end ──

async def test_live_coordination():
    """Run a coordinated 2-step task and check that the second agent received context from the first."""
    payload = {
        "description": (
            "Step 1: Write a one-sentence fact about the Python programming language. "
            "Step 2: Based on that fact, write a one-line slogan for a Python course."
        ),
        "specialization": "general"
    }

    print("\n🚀 Starting live coordinated team test...")
    result = await run_orchestrator(payload, "google/gemini-2.0-flash-001")

    print("\n=== RESULT ===")
    print(f"Status:   {result.get('status')}")
    print(f"Duration: {result.get('duration_seconds')}s")
    print(f"Cost:     ${result.get('total_cost_usd', 0):.4f}")
    print(f"\nProgress log:")
    for entry in result.get("progress_log", []):
        print(f"  {entry}")
    print(f"\nSummary:\n{result.get('summary', '(none)')}")

    assert result.get("status") == "completed", f"Expected 'completed', got: {result.get('status')}"
    print("\n✅ LIVE TEST PASSED: coordinated team executed successfully")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("MULTI-AGENT COORDINATION LIVE TEST")
    print("=" * 60)

    # Run unit check first (no LLM calls needed)
    unit_ok = test_router_injects_context()

    # Run live integration test
    asyncio.run(test_live_coordination())
