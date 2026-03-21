"""
Local GPU embedding for the worker node (worker-sigbin).
Uses sentence-transformers — no API cost, no network latency.

Phase 3 will optionally replace this with a vLLM embedding endpoint via LiteLLM.
The CNC node (Raspberry Pi) uses knowledge_base.py → OpenAI API instead.
"""
import os
import yaml
import logging

logger = logging.getLogger("Embeddings")

_embedder_instance = None  # singleton — model loads once, reused forever


def _load_embedding_config() -> dict:
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../config/profiles.yaml")
    )
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("task_routing", {}).get("embedding", {})


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
        self.model_name = cfg.get("worker_model", "nomic-ai/nomic-embed-text-v1.5")
        self.dim = cfg.get("worker_dim", 768)
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
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

    def embed(self, text: str) -> list[float]:
        """Return a normalized embedding vector for a single string."""
        self._ensure_loaded()
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return normalized embedding vectors for a list of strings (more efficient than looping)."""
        self._ensure_loaded()
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]
