import asyncio
import os
import sys
import yaml

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.iac.pulumi_wrapper import provision_worker, destroy_worker
from temporalio.client import Client

def get_temporal_host():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    settings_path = os.path.join(project_root, "config/settings.yaml")
    host = "127.0.0.1"
    port = 7233
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            settings = yaml.safe_load(f)
            if settings and "temporal" in settings:
                host = settings["temporal"].get("host", host)
                port = settings["temporal"].get("port", port)
    return f"{host}:{port}"

async def run_diagnostics():
    stack_name = "test-local-worker"
    project_name = "ai-orchestration"
    infra_id = "local_server_docker"
    
    print(f"🚀 [DIAGNOSTICS] Provisioning {infra_id}...")
    try:
        # 1. Provision the infrastructure
        outputs = await provision_worker(stack_name, project_name, infra_id, {})
        print(f"✅ [DIAGNOSTICS] Provisioning successful! Outputs: {outputs}")
        
        # 2. Connect to Temporal
        temporal_host = get_temporal_host()
        print(f"⏳ [DIAGNOSTICS] Waiting for Temporal to be available at {temporal_host}...")
        
        client = None
        # Retry logic for Temporal connection
        for i in range(12): # Wait up to 60 seconds (12 * 5)
            try:
                client = await Client.connect(temporal_host)
                print(f"✅ [DIAGNOSTICS] Connected to Temporal!")
                break
            except Exception as e:
                print(f"  Attempt {i+1}/12 - Temporal not ready yet: {e}")
                await asyncio.sleep(5)
                
        if not client:
            raise Exception("Failed to connect to Temporal after waiting.")
            
        # 3. Delegate a task
        task_input = "Run diagnostic self-test: Please return a simple confirmation that you received this task."
        print(f"🚀 [DIAGNOSTICS] Delegating task to ai-worker via Temporal...")
        
        # We need a unique workflow ID
        import uuid
        workflow_id = f"diag-task-{uuid.uuid4()}"
        
        handle = await client.start_workflow(
            "AIOrchestrationWorkflow",
            task_input,
            id=workflow_id,
            task_queue="ai-orchestration-queue"
        )
        
        print("\n⏳ [DIAGNOSTICS] Polling for worker progress...")
        last_progress = None
        
        # Poll for progress until workflow completes
        import time
        from temporalio.client import WorkflowExecutionStatus
        
        while True:
            desc = await handle.describe()
            if desc.status != WorkflowExecutionStatus.RUNNING:
                break
                
            if desc.raw_description.pending_activities:
                # Get the heartbeat details of the first pending activity
                act = desc.raw_description.pending_activities[0]
                if act.heartbeat_details:
                    # Temporal returns the details as an array of payloads
                    from temporalio.converter import default
                    try:
                        # Decode the protobuf Payload
                        payloads = act.heartbeat_details.payloads
                        current_progress = default().payload_converter.from_payloads(payloads)[0]
                        
                        if current_progress != last_progress:
                            print(f"📈 Worker Progress: {current_progress}")
                            last_progress = current_progress
                    except Exception as e:
                        print(f"Failed to decode heartbeat: {e}")
                        
            await asyncio.sleep(0.5)
            
        result = await handle.result()
        
        print("\n✅ [DIAGNOSTICS] Task execution complete!")
        if isinstance(result, dict):
            print("\n--- Assessment ---")
            print(result.get("assessment", "No assessment provided."))
            print("\n--- Recommendations ---")
            print(result.get("recommendations", "No recommendations provided."))
            print(f"Status: {result.get('status')}")
        else:
            print(f"Result: {result}")
            
    except Exception as e:
        print(f"❌ [DIAGNOSTICS] Failed: {e}")
        raise
        
    finally:
        print(f"\n🧹 [DIAGNOSTICS] Tearing down infrastructure...")
        try:
            # Destroy the infrastructure
            await destroy_worker(stack_name, project_name, infra_id)
            print(f"✅ [DIAGNOSTICS] Teardown complete!")
        except Exception as e:
            print(f"❌ [DIAGNOSTICS] Teardown failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
