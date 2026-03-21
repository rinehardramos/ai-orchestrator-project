import os
import sys
import uuid
import yaml
import re

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
import requests as _requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

# Embedding dimensions per provider model
_EMBED_DIM = 1536   # text-embedding-3-small


class KnowledgeBaseClient:
    """
    Lightweight embedding client for the CNC (Genesis) node.
    Uses direct HTTP calls to embedding APIs — no heavy ML libraries required.
    Supported providers: Google (text-embedding-004), OpenAI (text-embedding-3-small).
    """

    def __init__(self, settings_path=None):
        if settings_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            settings_path = os.path.join(project_root, "config/settings.yaml")

        qdrant_url = os.environ.get("QDRANT_URL")
        if not qdrant_url and os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                settings = yaml.safe_load(f)
                if settings and "qdrant" in settings:
                    host = settings["qdrant"].get("host", "localhost")
                    port = settings["qdrant"].get("port", 6333)
                    qdrant_url = f"http://{host}:{port}"

        self.store = HybridMemoryStore(qdrant_url=qdrant_url)
        self.collection_name = "knowledge_base_v2"

        self._openai_key = os.environ.get("OPENAI_API_KEY")
        self._embed_dim = _EMBED_DIM

    def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector via direct HTTP API call."""
        try:
            return self._embed_openai(text)
        except Exception as e:
            print(f"Error generating embedding (openai): {e}")
        return [0.0] * self._embed_dim

    def _embed_openai(self, text: str) -> list[float]:
        resp = _requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._openai_key}"},
            json={"model": "text-embedding-3-small", "input": text},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    def close(self):
        """No-op: kept for API compatibility."""
        pass

    def ingest_markdown(self, filepath: str):
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return

        with open(filepath, 'r') as f:
            content = f.read()

        # Split by markdown headers
        sections = re.split(r'\n## ', content)
        if len(sections) > 1:
            sections = sections[1:] # Skip the title part
        
        print(f"Found {len(sections)} sections to ingest.")
        for section in sections:
            lines = section.strip().split('\n')
            if not lines:
                continue
            title = lines[0].strip()
            body = '\n'.join(lines[1:]).strip()
            
            # Combine for embedding
            full_text = f"Issue: {title}\n{body}"
            vector = self.embed_text(full_text)
            
            entry = MemoryEntry(
                id=str(uuid.uuid4()),
                content=full_text,
                metadata={"title": title, "source": "KNOWLEDGE_BASE.md", "score": 1.0}
            )
            
            self.store.store_l2(self.collection_name, entry, vector)
            print(f"✅ Ingested: {title}")

    def query_similar_issues(self, task_description: str, limit: int = 2) -> list[dict]:
        vector = self.embed_text(task_description)
        results = self.store.query_l2(self.collection_name, vector, limit)
        
        relevant_issues = []
        for res in results:
            if res.score > 0.7: # Threshold for relevance
                payload = res.payload or {}
                
                # ── Boost Score On Retrieval ──
                # If this knowledge is useful, reset its belief score so it outlives decay.
                try:
                    if "score" in payload:
                        new_score = min(1.0, payload.get("score", 1.0) + 0.1) # Boost
                        self.store.qdrant.set_payload(
                            collection_name=self.collection_name,
                            payload={"score": new_score},
                            points=[res.id]
                        )
                except Exception as e:
                    print(f"Failed to boost score for {res.id}: {e}")

                relevant_issues.append({
                    "title": payload.get("title", ""),
                    "content": payload.get("content", ""),
                    "belief_score": payload.get("score", 1.0),
                    "similarity": res.score
                })
        return relevant_issues

if __name__ == "__main__":
    kb = KnowledgeBaseClient()
    kb.ingest_markdown("KNOWLEDGE_BASE.md")
