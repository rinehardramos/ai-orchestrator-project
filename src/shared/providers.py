"""
Provider Manager - Load and manage LLM/embedding providers from database.

Providers are user-configurable and stored in the `providers` table.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Provider:
    """Provider configuration."""
    id: int
    name: str
    display_name: str
    provider_type: str  # openai_compatible, google_native, anthropic_native, openai_native
    api_base: Optional[str]
    api_key_env_var: Optional[str]
    is_local: bool
    is_active: bool
    default_headers: Dict[str, str]
    config: Dict[str, Any]


class ProviderManager:
    """Manage LLM/embedding providers from database."""
    
    def __init__(self):
        self._providers: Dict[str, Provider] = {}
        self._loaded = False
    
    def _ensure_loaded(self):
        if self._loaded:
            return
        
        try:
            from src.config_db import get_loader
            loader = get_loader()
            conn = loader._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT id, name, display_name, provider_type, api_base, 
                       api_key_env_var, is_local, is_active, default_headers, config
                FROM providers
                WHERE is_active = true
            """)
            
            for row in cur.fetchall():
                provider = Provider(
                    id=row[0],
                    name=row[1],
                    display_name=row[2],
                    provider_type=row[3],
                    api_base=row[4],
                    api_key_env_var=row[5],
                    is_local=row[6],
                    is_active=row[7],
                    default_headers=row[8] or {},
                    config=row[9] or {}
                )
                self._providers[provider.name] = provider
            
            self._loaded = True
            logger.info(f"Loaded {len(self._providers)} providers: {list(self._providers.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to load providers: {e}")
            self._load_defaults()
    
    def _load_defaults(self):
        """Load hardcoded defaults if database is unavailable."""
        defaults = [
            Provider(0, "lmstudio", "LM Studio", "openai_compatible", 
                     "http://localhost:1234/v1", "LMSTUDIO_API_KEY", True, True, {}, {}),
            Provider(1, "ollama", "Ollama", "openai_compatible",
                     "http://localhost:11434/v1", "OLLAMA_API_KEY", True, True, {}, {}),
            Provider(2, "openrouter", "OpenRouter", "openai_compatible",
                     "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", False, True, {}, {}),
            Provider(3, "google", "Google Gemini", "google_native",
                     None, "GOOGLE_API_KEY", False, True, {}, {}),
            Provider(4, "openai", "OpenAI", "openai_native",
                     "https://api.openai.com/v1", "OPENAI_API_KEY", False, True, {}, {}),
            Provider(5, "anthropic", "Anthropic", "anthropic_native",
                     "https://api.anthropic.com", "ANTHROPIC_API_KEY", False, True, {}, {}),
        ]
        for p in defaults:
            self._providers[p.name] = p
        self._loaded = True
    
    def get_provider(self, name: str) -> Optional[Provider]:
        """Get provider by name."""
        self._ensure_loaded()
        return self._providers.get(name)
    
    def get_all_providers(self) -> Dict[str, Provider]:
        """Get all active providers."""
        self._ensure_loaded()
        return self._providers.copy()
    
    def get_api_key(self, provider_name: str) -> Optional[str]:
        """Get API key for a provider from environment."""
        provider = self.get_provider(provider_name)
        if not provider:
            return None
        
        if provider.api_key_env_var:
            return os.environ.get(provider.api_key_env_var)
        
        return None
    
    def get_api_base(self, provider_name: str) -> Optional[str]:
        """Get API base URL for a provider."""
        provider = self.get_provider(provider_name)
        if not provider:
            return None
        
        # For local providers, check config for host/port override
        if provider.is_local and provider.config:
            host = provider.config.get("host", "localhost")
            port = provider.config.get("port")
            if port:
                return f"http://{host}:{port}/v1"
        
        return provider.api_base
    
    def is_openai_compatible(self, provider_name: str) -> bool:
        """Check if provider uses OpenAI-compatible API."""
        provider = self.get_provider(provider_name)
        return provider and provider.provider_type == "openai_compatible"
    
    def refresh(self):
        """Force reload providers from database."""
        self._loaded = False
        self._providers.clear()
        self._ensure_loaded()


# Singleton instance
_provider_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Get the singleton provider manager."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager


def get_provider(name: str) -> Optional[Provider]:
    """Convenience function to get a provider."""
    return get_provider_manager().get_provider(name)
