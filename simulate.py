import asyncio
from central_node.worker import graph

async def run_simulation():
    task = "assess the improvements on the current ai orchestration and worker system..."
    initial_state = {"input_task": task, "assessment": "", "recommendations": "", "status": "started"}
    
    print("🚀 [GENESIS L0] Sending task to Central Node Langgraph Worker...")
    final_state = await graph.ainvoke(initial_state)
    
    print("\n✅ [CENTRAL NODE] Worker Execution Complete.")
    print("\n--- Assessment ---")
    print(final_state["assessment"])
    print("\n--- Recommendations ---")
    print(final_state["recommendations"])

if __name__ == "__main__":
    asyncio.run(run_simulation())
