import asyncio
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import SearchAttributes

async def main():
    try:
        client = await Client.connect("localhost:7233")
        print("Connected to Temporal.")
        
        print("Listing AIOrchestrationWorkflow executions...")
        # Since we just want recent, we can list all or recent
        async for wf in client.list_workflows('WorkflowType="AIOrchestrationWorkflow"'):
            print(f"Workflow ID: {wf.id}, Status: {wf.status}")
            try:
                # Let's try to describe it
                handle = client.get_workflow_handle(wf.id)
                desc = await handle.describe()
                print(f"  Description: {desc}")
                print(f"  Pending Activities: {desc.raw_description.pending_activities}")
                # Wait, getting the argument is not straight-forward. Let's see if memo or search attributes has it.
                print(f"  Memo: {desc.memo}")
                print(f"  Search Attributes: {desc.search_attributes}")
            except Exception as e:
                print(f"  Describe error: {e}")
            break
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
