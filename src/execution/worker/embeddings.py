"""
Dual embedding module for all agents (worker, genesis, control).
Supports separate models for code and text content.

Uses provider config from database to determine embedding endpoints.
All agents use the same embedding model for vector compatibility in Qdrant.
"""
import os
import re
import logging
from typing import Literal
from dataclasses import dataclass

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


@dataclass
class EmbeddingConfig:
    """Configuration for a single embedding model."""
    model: str
    provider: str
    dim: int
    api_base: str = None
    is_local: bool = True


def _load_dual_embedding_config() -> dict[str, EmbeddingConfig]:
    """Load dual embedding config from database.
    
    Expected config structure in app_config:
    namespace: 'profiles', key: 'task_routing'
    value.embeddings_text: {model, provider, dim}
    value.embeddings_code: {model, provider, dim}
    
    Returns dict with 'text' and 'code' keys.
    """
    configs = {}
    
    try:
        from src.config_db import get_loader
        from src.shared.providers import get_provider
        loader = get_loader()
        profiles = loader.load_namespace("profiles")
        task_routing = profiles.get("task_routing", {})
        
        for embed_type in ["text", "code"]:
            emb_key = f"embeddings_{embed_type}"
            emb_config = task_routing.get(emb_key, {})
            
            if emb_config:
                provider_name = emb_config.get("provider", "lmstudio")
                provider = get_provider(provider_name)
                
                config = EmbeddingConfig(
                    model=emb_config.get("model", "nomic-embed-text-v1.5"),
                    provider=provider_name,
                    dim=emb_config.get("dim", 768),
                    is_local=provider.is_local if provider else True
                )
                
                # Determine API base with environment variable override for Docker
                if provider_name in ["lmstudio", "ollama", "local"]:
                    env_host = os.environ.get(f"{provider_name.upper()}_HOST")
                    env_port = os.environ.get(f"{provider_name.upper()}_PORT", "1234")
                    if env_host:
                        config.api_base = f"http://{env_host}:{env_port}/v1"
                    elif provider and provider.api_base:
                        config.api_base = provider.api_base
                    elif provider and provider.config:
                        host = provider.config.get("host", "localhost")
                        port = provider.config.get("port", "1234")
                        config.api_base = f"http://{host}:{port}/v1"
                    else:
                        # Final fallback to environment variables
                        fallback_host = os.environ.get("LMSTUDIO_HOST", os.environ.get("OLLAMA_HOST", "localhost"))
                        fallback_port = os.environ.get("LMSTUDIO_PORT", os.environ.get("OLLAMA_PORT", "1234"))
                        config.api_base = f"http://{fallback_host}:{fallback_port}/v1"
                elif provider:
                    config.api_base = provider.api_base
                
                configs[embed_type] = config
                logger.info(f"Loaded {embed_type} embedding: model={config.model}, provider={config.provider}, dim={config.dim}")
        
        if not configs:
            raise ValueError("No embedding configs found in database")
            
    except Exception as e:
        logger.error(f"Could not load embedding config from DB: {e}")
        configs = _get_default_configs()
    
    return configs


def _get_default_configs() -> dict[str, EmbeddingConfig]:
    """Default embedding configurations with environment variable override."""
    lmstudio_host = os.environ.get("LMSTUDIO_HOST", "localhost")
    lmstudio_port = os.environ.get("LMSTUDIO_PORT", "1234")
    api_base = f"http://{lmstudio_host}:{lmstudio_port}/v1"
    
    return {
        "text": EmbeddingConfig(
            model="nomic-embed-text-v1.5",
            provider="lmstudio",
            dim=768,
            api_base=api_base,
            is_local=True
        ),
        "code": EmbeddingConfig(
            model="nomic-embed-code",
            provider="lmstudio",
            dim=3584,
            api_base=api_base,
            is_local=True
        )
    }


def classify_content(text: str) -> Literal["text", "code"]:
    """Classify content as code or text.
    
    Uses heuristics to detect code content:
    - Code block markers
    - Programming keywords/patterns
    - File extensions in metadata
    """
    code_indicators = [
        r'```[\w]*',  # Code blocks
        r'^\s*(def|class|function|import|export|const|let|var)\s',
        r'^\s*(if|for|while|try|catch)\s*[\({]',
        r'[{}\[\];]\s*$',  # Brackets at line end
        r'->\s*\w+',  # Arrow functions
        r'=>\s*\{',  # JS arrow functions
        r'::\s*\w+',  # Rust/PHP syntax
        r'<\w+>',  # HTML/JSX tags
        r'#include|#import|using\s+',  # C/C#/Java imports
        r'from\s+\w+\s+import',  # Python imports
    ]
    
    lines = text.split('\n')
    code_lines = 0
    
    for line in lines:
        for pattern in code_indicators:
            if re.search(pattern, line, re.MULTILINE):
                code_lines += 1
                break
    
    code_ratio = code_lines / max(len(lines), 1)
    return "code" if code_ratio > 0.15 else "text"


def get_embedder() -> "DualEmbedder":
    """
    Return the singleton dual embedder.
    """
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = DualEmbedder()
    return _embedder_instance


class DualEmbedder:
    """Manages two embedding models: one for code, one for text."""

    def __init__(self):
        self._configs = _load_dual_embedding_config()
        self._models = {}  # Lazy loaded
        self._api_bases = {}

    def _get_model(self, embed_type: Literal["text", "code"]) -> tuple:
        """Get model instance and config for embedding type."""
        if embed_type not in self._configs:
            embed_type = "text"  # Fallback to text
        
        config = self._configs[embed_type]
        return config, self._get_or_create_model(config)
    
    def _get_or_create_model(self, config: EmbeddingConfig):
        """Get or create model for the given config."""
        key = f"{config.provider}:{config.model}"
        
        if key in self._models:
            return self._models[key]
        
        if config.provider in ["local", "lmstudio", "ollama"]:
            self._api_bases[key] = config.api_base
            self._models[key] = "api"  # Placeholder for API-based
        else:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model {config.model} ...")
                self._models[key] = SentenceTransformer(config.model, trust_remote_code=True)
                logger.info("Embedding model ready.")
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "This module only runs on worker-sigbin. "
                    "The CNC node uses knowledge_base.py → OpenAI API for embeddings."
                )
        
        return self._models[key]
    
    def _embed_via_api(self, texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
        """Embed texts via API call."""
        import requests
        
        resp = requests.post(
            f"{config.api_base}/embeddings",
            headers={"Authorization": "Bearer lmstudio"},
            json={"model": config.model, "input": texts},
            timeout=30,
        )
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]
    
    @track(name="embed_text")
    def embed(self, text: str, embed_type: Literal["text", "code", "auto"] = "auto") -> list[float]:
        """Return a normalized embedding vector for a single string."""
        if embed_type == "auto":
            embed_type = classify_content(text)
        
        config, model = self._get_model(embed_type)
        
        if config.provider in ["local", "lmstudio", "ollama"]:
            result = self._embed_via_api([text], config)
            return result[0]
        
        return model.encode(text, normalize_embeddings=True).tolist()

    @track(name="embed_batch")
    def embed_batch(
        self, 
        texts: list[str], 
        embed_type: Literal["text", "code", "auto"] = "auto"
    ) -> list[list[float]]:
        """Return normalized embedding vectors for a list of strings."""
        if not texts:
            return []
        
        if embed_type == "auto":
            embed_type = classify_content(" ".join(texts[:5]))  # Sample first few
        
        config, model = self._get_model(embed_type)
        
        if config.provider in ["local", "lmstudio", "ollama"]:
            return self._embed_via_api(texts, config)
        
        return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]
    
    def get_config(self, embed_type: Literal["text", "code"]) -> EmbeddingConfig:
        """Get config for specific embedding type."""
        return self._configs.get(embed_type)
    
    def get_collection_name(self, embed_type: Literal["text", "code"]) -> str:
        """Get Qdrant collection name for embedding type."""
        return f"knowledge_{embed_type}_v1"


# Backwards compatibility
class SentenceTransformerEmbedder:
    """Legacy wrapper for backwards compatibility."""
    
    def __init__(self):
        self._dual = get_embedder()
        cfg = self._dual.get_config("text")
        self.model_name = cfg.model
        self.dim = cfg.dim

    def embed(self, text: str) -> list[float]:
        return self._dual.embed(text, "text")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._dual.embed_batch(texts, "text")
