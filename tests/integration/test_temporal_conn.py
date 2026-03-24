import asyncio
import os
from temporalio.client import Client
from src.config import load_settings

async def test_temporal_connection():
    config = load_settings()
    temp_cfg = config.get("temporal", {})
    host = temp_cfg.get("host", "localhost")
    port = temp_cfg.get("port", 7233)
    target = f"{host}:{port}"
    
    print(f"Attempting to connect to Temporal at {target}...")
    try:
        client = await asyncio.wait_for(Client.connect(target), timeout=10.0)
        print("✅ Successfully connected to Temporal!")
        
        # Try to list workflows to verify communication
        print("Listing recent workflows...")
        async for workflow in client.list_workflows(query='ExecutionStatus = "Running"'):
            print(f" - ID: {workflow.id}, Type: {workflow.workflow_type}")
            
    except asyncio.TimeoutError:
        print("❌ Connection to Temporal TIMED OUT.")
    except Exception as e:
        print(f"❌ Connection to Temporal FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_temporal_connection())
