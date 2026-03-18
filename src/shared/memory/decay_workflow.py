import asyncio
import os
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

DECAY_FACTOR = 0.95

@activity.defn
async def apply_belief_decay() -> dict:
    """
    Retrieves all subjective observations from Qdrant and applies a decay factor
    to their 'score' metadata, reducing the systemic impact of stale knowledge.
    """
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
    from src.shared.memory.hybrid_store import HybridMemoryStore
    
    memory_store = HybridMemoryStore()
    if not memory_store.qdrant:
        return {"status": "skipped", "reason": "Qdrant not configured"}
        
    collections_to_decay = ["agent_insights", "knowledge_base"]
    total_decayed = 0
    
    for collection_name in collections_to_decay:
        # Check if collection exists
        try:
            memory_store.qdrant.get_collection(collection_name)
        except Exception:
            print(f"Skipping {collection_name}: does not exist.")
            continue

        offset = None
        while True:
            records, next_offset = memory_store.qdrant.scroll(
                collection_name=collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            
            for record in records:
                payload = record.payload or {}
                if "score" in payload:
                    new_score = payload["score"] * DECAY_FACTOR
                    memory_store.qdrant.set_payload(
                        collection_name=collection_name,
                        payload={"score": new_score},
                        points=[record.id]
                    )
                    total_decayed += 1
                
            if next_offset is None:
                break
            offset = next_offset

    print(f"✅ Applied belief decay ({DECAY_FACTOR}) to {total_decayed} records across collections.")
    return {"status": "success", "decayed_records": total_decayed}

@workflow.defn
class BeliefDecayWorkflow:
    @workflow.run
    async def run(self) -> dict:
        result = await workflow.execute_activity(
            apply_belief_decay,
            start_to_close_timeout=timedelta(minutes=5)
        )
        return result

async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
    client = await Client.connect(temporal_host)

    worker = Worker(
        client,
        task_queue="ai-orchestration-queue", # Run on the same queue so existing workers can process it, or create a dedicated one.
        workflows=[BeliefDecayWorkflow],
        activities=[apply_belief_decay],
        workflow_runner=UnsandboxedWorkflowRunner()
    )
    
    # We don't start the worker here typically; this file defines it.
    # The actual execution could be triggered by CNC or run standalone.
    # We will just print instructions.
    print("Belief Decay workflow defined.")

if __name__ == "__main__":
    asyncio.run(main())
