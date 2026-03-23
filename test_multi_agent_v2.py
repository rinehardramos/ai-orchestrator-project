import asyncio
import logging
import os
import sys
import uuid

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from src.execution.worker.multi_agent_graph import run_orchestrator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestMultiAgentV2")

async def run_test():
    """
    Simulates a complex marketing campaign task to verify:
    1. Multi-agent decomposition.
    2. Native Google (Gemini) provider integration.
    3. Context sharing (upstream results passed to downstream agents).
    """
    
    # Using a multi-step prompt that forces sequential dependency
    campaign_prompt = (
        "Launch a marketing campaign for a premium eco-friendly water bottle. "
        "First, perform market research and provide target demographics. "
        "Second, based on that research, create a catchy visual for a billboard (image gen) "
        "and draft three promotional social media posts (copywriting). "
        "Finally, conduct a quality control review of the copy and visuals. "
        "Ensure each agent receives the context from its predecessors."
    )
    
    payload = {
        "description": campaign_prompt
    }
    
    logger.info("🚀 Starting Multi-Agent V2 Test (Native Google Provider)...")
    
    try:
        # We pass a placeholder model_id; the actual routing comes from profiles.yaml
        result = await run_orchestrator(payload, "gemini-3-flash")
        
        print("\n" + "="*50)
        print("🏆 CAMPAIGN TEST COMPLETED")
        print("="*50)
        print(f"Status: {result.get('status')}")
        print(f"Total Cost: ${result.get('total_cost_usd', 0):.5f}")
        print(f"Duration: {result.get('duration_seconds')}s")
        print("\n--- FINAL SUMMARY ---")
        print(result.get("summary", "No summary found."))
        
        if result.get("status") == "completed":
            print("\n✅ Verfication SUCCESS")
        else:
            print(f"\n❌ Verification FAILED: {result.get('summary')}")
            
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
