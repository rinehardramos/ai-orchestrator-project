import os
import sys
import uuid
import yaml
import re

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
from google import genai
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

class KnowledgeBaseClient:
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
        self.collection_name = "knowledge_base"
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.embedding_model = "gemini-embedding-001"

    def embed_text(self, text: str) -> list[float]:
        try:
            response = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text
            )
            return response.embeddings[0].values
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return [0.0] * 768 # Default empty vector if API key is missing

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
