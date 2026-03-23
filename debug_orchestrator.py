import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from src.execution.worker.multi_agent_graph import run_orchestrator

logging.basicConfig(level=logging.INFO)

async def test():
    payload = {
        "description": "Tell me a short joke about AI.",
        "specialization": "general"
    }
    try:
        result = await run_orchestrator(payload, "google/gemini-2.0-flash-001")
        print("\n=== RESULT ===")
        print(result)
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
