"""
Shared embedding module for all agents (worker, genesis, control).
Uses local LMStudio embedding endpoint for code-aware embeddings.

All agents use the same embedding model for vector compatibility in Qdrant.
"""
import os
import yaml
import logging

logger = logging.getLogger("Embeddings")

_embedder_instance = None

try:
    from opik import track
    OPIK_AVAILABLE = True
except ImportError:
    OPIK_AVAILABLE = False
    def track(**kwargs):
        def decorator(fn):
            return fn
        return decorator


def _load_embedding_config() -> dict:
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../config/profiles.yaml")
    )
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("task_routing", {}).get("embeddings", {})


def get_embedder() -> "SentenceTransformerEmbedder":
    """
    Return the singleton embedder.
    Model downloads and loads on first call (~2-5 seconds on GPU).
    All subsequent calls are instant.
    """
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = SentenceTransformerEmbedder()
    return _embedder_instance


class SentenceTransformerEmbedder:

    def __init__(self):
        cfg = _load_embedding_config()
        self.model_name = cfg.get("model", "nomic-embed-code")
        self.dim = cfg.get("dim", 3584)
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
            
        cfg = _load_embedding_config()
        self.provider = cfg.get("provider", "lmstudio")
        
        if self.provider in ["local", "lmstudio", "ollama"]:
            # Load URL from settings
            settings_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config/settings.yaml"))
            self.api_base = "http://127.0.0.1:1234/v1"
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = yaml.safe_load(f)
                    env = settings.get("active_environment", "primary")
                    lmstudio = settings.get("environments", {}).get(env, {}).get("lmstudio", {})
                    if lmstudio:
                        self.api_base = f"http://{lmstudio.get('host', '127.0.0.1')}:{lmstudio.get('port', 1234)}/v1"
            logger.info(f"Using local embeddings endpoint at {self.api_base}")
            self._model = "local" # placeholder
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "This module only runs on worker-sigbin. "
                "The CNC node uses knowledge_base.py → OpenAI API for embeddings."
            )
        logger.info(f"Loading embedding model {self.model_name} ...")
        self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
        logger.info("Embedding model ready.")

    @track(name="embed_text")
    def embed(self, text: str) -> list[float]:
        """Return a normalized embedding vector for a single string."""
        self._ensure_loaded()
        
        if getattr(self, "provider", "") in ["local", "lmstudio", "ollama"]:
            import requests
            resp = requests.post(
                f"{self.api_base}/embeddings",
                headers={"Authorization": "Bearer lmstudio"},
                json={"model": self.model_name, "input": text},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

        return self._model.encode(text, normalize_embeddings=True).tolist()

    @track(name="embed_batch")
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return normalized embedding vectors for a list of strings (more efficient than looping)."""
        self._ensure_loaded()
        if getattr(self, "provider", "") in ["local", "lmstudio", "ollama"]:
            import requests
            resp = requests.post(
                f"{self.api_base}/embeddings",
                headers={"Authorization": "Bearer lmstudio"},
                json={"model": self.model_name, "input": texts},
                timeout=15,
            )
            resp.raise_for_status()
            return [data["embedding"] for data in resp.json()["data"]]

        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]
