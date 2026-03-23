"""
Verify all three orchestration strategies:
  1. single_agent
  2. parallel_isolated
  3. coordinated_team (with dependency context injection)
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")

from src.execution.worker.multi_agent_graph import run_orchestrator

SEP = "=" * 60

async def run(label: str, description: str):
    print(f"\n{SEP}")
    print(f"TEST: {label}")
    print(SEP)
    result = await run_orchestrator({"description": description, "specialization": "general"}, "google/gemini-2.0-flash-001")
    print(f"  Status   : {result.get('status')}")
    print(f"  Strategy : {next((l for l in result.get('progress_log', []) if 'strategy' in l), 'n/a')}")
    print(f"  Duration : {result.get('duration_seconds')}s")
    print(f"  Cost     : ${result.get('total_cost_usd', 0):.4f}")
    print(f"  Workers  : {result.get('tool_call_count', 0)}")
    print(f"\n  Summary:\n{result.get('summary', '(none)')[:600]}")
    assert result.get("status") == "completed", f"FAILED — status: {result.get('status')}"
    print(f"\n  ✅ PASSED")
    return result

async def main():
    # 1. Single agent — simple task, no decomposition needed
    await run(
        "1. SINGLE AGENT",
        "Tell me a one-sentence fun fact about the Moon."
    )

    # 2. Parallel isolated — two independent tasks
    await run(
        "2. PARALLEL ISOLATED",
        "Do two independent things: (A) Write a haiku about the ocean. (B) Write a haiku about mountains. These are completely independent."
    )

    # 3. Coordinated team — step B depends on step A output
    await run(
        "3. COORDINATED TEAM (dependency chain)",
        "First, research and write one interesting fact about the Python programming language. "
        "Then, based on that specific fact, write a one-sentence marketing slogan for a Python bootcamp."
    )

    print(f"\n{SEP}")
    print("ALL THREE STRATEGIES PASSED ✅")
    print(SEP)

if __name__ == "__main__":
    asyncio.run(main())
