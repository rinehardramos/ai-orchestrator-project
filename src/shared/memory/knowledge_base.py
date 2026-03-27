import os
import sys
import uuid
import yaml
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
import requests as _requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

try:
    from opik import track
    OPIK_AVAILABLE = True
except ImportError:
    OPIK_AVAILABLE = False
    def track(**kwargs):
        def decorator(fn):
            return fn
        return decorator

def _configure_opik():
    import logging
    logger = logging.getLogger("KnowledgeBase")
    
    try:
        from src.config import load_settings
        load_settings()
    except Exception:
        pass
        
    url_override = os.environ.get("OPIK_URL_OVERRIDE")
    if url_override and OPIK_AVAILABLE:
        try:
            import opik
            opik.configure(use_local=True, url=url_override)
            logger.info(f"[OPIK] Configured for self-hosted at '{url_override}'")
        except Exception as e:
            logger.warning(f"[OPIK] Configuration failed: {e}")

# _configure_opik will be called in __init__

# Embedding dimensions per provider model
_EMBED_DIM = 3584   # nomic-embed-code


class KnowledgeBaseClient:
    """
    Shared embedding client for all agents (worker, genesis, control).
    Uses direct HTTP calls to local LMStudio embedding endpoint.
    All agents use the same embedding model for vector compatibility in Qdrant.
    """

    def __init__(self, settings_path=None):
        _configure_opik()
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if settings_path is None:
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
        
        # Get collection name from database config
        try:
            from src.config_db import get_loader
            loader = get_loader()
            config = loader.load_namespace("knowledge") or {}
            self.collection_name = config.get("knowledge_collection", "knowledge_v1")
        except Exception:
            self.collection_name = "knowledge_v1"

        self._openai_key = os.environ.get("OPENAI_API_KEY", "dummy")
        
        # Default to LMStudio for embeddings
        self._embed_model = "text-embedding-nomic-embed-code"
        self._embed_dim = _EMBED_DIM
        lmstudio_host = os.environ.get("LMSTUDIO_HOST", "localhost")
        lmstudio_port = os.environ.get("LMSTUDIO_PORT", "1234")
        self._api_base = f"http://{lmstudio_host}:{lmstudio_port}/v1"
        self._embed_provider = "lmstudio"
        self._openai_key = "lmstudio"
        
        try:
            from src.config_db import get_loader
            loader = get_loader()
            profiles = loader.load_namespace("profiles")
            emb = profiles.get("task_routing", {}).get("embeddings", {})
            
            if emb:
                self._embed_provider = emb.get("provider", "lmstudio")
                self._embed_model = emb.get("model", "text-embedding-nomic-embed-code")
                self._embed_dim = emb.get("dim", _EMBED_DIM)
        except Exception as e:
            # Fallback to YAML if database not available
            profiles_path = os.path.join(project_root, "config/profiles.yaml")
            if os.path.exists(profiles_path):
                with open(profiles_path, 'r') as f:
                    prof = yaml.safe_load(f)
                    emb = prof.get("task_routing", {}).get("embeddings", {})
                    if emb:
                        self._embed_provider = emb.get("provider", "lmstudio")
                        self._embed_model = emb.get("model", "text-embedding-nomic-embed-code")
                        self._embed_dim = emb.get("dim", _EMBED_DIM)
        
        # Set API endpoint based on provider
        if self._embed_provider in ["local", "lmstudio", "ollama"]:
            # Get host/port from environment variables first
            host = os.environ.get("LMSTUDIO_HOST", os.environ.get("OLLAMA_HOST", "localhost"))
            port = os.environ.get("LMSTUDIO_PORT", os.environ.get("OLLAMA_PORT", "1234"))
            self._api_base = f"http://{host}:{port}/v1"
            self._openai_key = "lmstudio"
            
            # Check settings.yaml for custom host/port (fallback)
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    settings = yaml.safe_load(f)
                    env = settings.get("active_environment", "primary")
                    lmstudio = settings.get("environments", {}).get(env, {}).get("lmstudio", {})
                    if lmstudio and not os.environ.get("LMSTUDIO_HOST"):
                        host = lmstudio.get('host', 'localhost')
                        port = lmstudio.get('port', 1234)
                        self._api_base = f"http://{host}:{port}/v1"

    @track(name="embed_text")
    def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector via direct HTTP API call."""
        try:
            return self._embed_openai(text)
        except Exception as e:
            print(f"Error generating embedding (openai): {e}")
        return [0.0] * self._embed_dim

    def _embed_openai(self, text: str) -> list[float]:
        resp = _requests.post(
            f"{self._api_base}/embeddings",
            headers={"Authorization": f"Bearer {self._openai_key}"},
            json={"model": self._embed_model, "input": text},
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
        # Use KnowledgeStore for named vector support
        try:
            from src.shared.memory.knowledge_store import KnowledgeStore
            store = KnowledgeStore()
            results = store.query(task_description, limit=limit)
            
            relevant_issues = []
            for res in results:
                if res.get("score", 0) > 0.3:
                    relevant_issues.append({
                        "title": res.get("section_title", res.get("doc_name", "")),
                        "content": res.get("text", ""),
                        "doc_name": res.get("doc_name", ""),
                        "score": res.get("score", 0),
                        "similarity": res.get("score", 0)
                    })
            return relevant_issues
        except Exception as e:
            # Fallback to HybridMemoryStore for single-vector collections
            vector = self.embed_text(task_description)
            results = self.store.query_l2(self.collection_name, vector, limit)
            
            relevant_issues = []
            for res in results:
                if res.score > 0.3:
                    payload = res.payload or {}
                    relevant_issues.append({
                        "title": payload.get("title", ""),
                        "content": payload.get("content", ""),
                        "belief_score": payload.get("score", 1.0),
                        "score": res.score,
                        "similarity": res.score
                    })
            return relevant_issues

if __name__ == "__main__":
    kb = KnowledgeBaseClient()
    kb.ingest_markdown("KNOWLEDGE_BASE.md")
