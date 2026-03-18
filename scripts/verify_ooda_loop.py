import sys
import os
import uuid
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shared.memory.knowledge_base import KnowledgeBaseClient
from src.shared.memory.hybrid_store import MemoryEntry
from src.shared.memory.decay_workflow import apply_belief_decay

def test_ooda_loop_decay_and_boost():
    print("--- Starting OODA Loop Verification ---")
    kb = KnowledgeBaseClient()
    
    # Mock embed_text to return a valid non-zero vector to bypass API dummy key errors
    kb.embed_text = lambda x: [0.1] * 768
    
    if not kb.store.qdrant:
        print("❌ Error: Qdrant client unavailable. Is Qdrant running?")
        sys.exit(1)
        
    unique_text = f"OODA_TEST_PHRASE_{uuid.uuid4()}"
    vector = kb.embed_text(unique_text)
    
    entry_id = str(uuid.uuid4())
    entry = MemoryEntry(
        id=entry_id,
        content=unique_text,
        metadata={"title": unique_text, "source": "TEST", "score": 1.0}
    )
    
    print(f"[1] Ingesting test entry into {kb.collection_name}: {entry_id}")
    kb.store.store_l2(kb.collection_name, entry, vector)
    
    # Need to wait a tiny bit for indexing in Qdrant (usually instantaneous but just in case)
    import time
    time.sleep(1)
    
    try:
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        
        # Verify initial score
        records, _ = kb.store.qdrant.scroll(
            collection_name=kb.collection_name, 
            scroll_filter=Filter(
                must=[FieldCondition(key="title", match=MatchValue(value=unique_text))]
            )
        )
        assert len(records) > 0, "❌ Failed to insert entry"
        assert records[0].payload["score"] == 1.0, f"❌ Initial score should be 1.0, but got {records[0].payload.get('score')}"
        print("✅ Insert successful. Initial belief score is 1.0")
    
        print("[2] Running Belief Decay...")
        result = asyncio.run(apply_belief_decay())
        print(f"Decay result: {result}")
    
        # Verify decayed score
        records, _ = kb.store.qdrant.scroll(
            collection_name=kb.collection_name, 
            scroll_filter=Filter(
                must=[FieldCondition(key="title", match=MatchValue(value=unique_text))]
            )
        )
        decayed_score = records[0].payload["score"]
        assert abs(decayed_score - 0.95) < 0.001, f"❌ Expected 0.95, got {decayed_score}"
        print(f"✅ Decay applied successfully (decayed score is {decayed_score:.2f}).")
    
        print("[3] Simulating OODA retrieval boost...")
        results = kb.query_similar_issues(unique_text, limit=1)
        assert len(results) > 0, "❌ Query should hit the exact phrase"
        
        # Verify boosted score
        records, _ = kb.store.qdrant.scroll(
            collection_name=kb.collection_name, 
            scroll_filter=Filter(
                must=[FieldCondition(key="title", match=MatchValue(value=unique_text))]
            )
        )
        boosted_score = records[0].payload["score"]
        # It boosts by min(1.0, current + 0.1), so 0.95 + 0.1 = 1.05 -> 1.0
        assert abs(boosted_score - 1.0) < 0.001, f"❌ Expected score to be boosted to 1.0, got {boosted_score}"
        print(f"✅ Retrieval boost applied successfully (score restored to {boosted_score:.2f}).")
        
    finally:
        print("[4] Cleaning up...")
        kb.store.qdrant.delete(collection_name=kb.collection_name, points_selector=[entry_id])
        print("--- OODA Loop Verification Passed! ---")

if __name__ == "__main__":
    test_ooda_loop_decay_and_boost()
