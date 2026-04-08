import os
import logging
from dotenv import load_dotenv
from src.config_db import get_loader

# Ensure environment variables are loaded from .env
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(project_root, ".env"))

log = logging.getLogger(__name__)

def load_settings(env_name: str = None):
    """
    Centralized configuration loader.
    Merges configuration from DB (app_config table) with sensitive
    environment variables loaded from .env or os.environ.
    """
    try:
        # Load structural configuration from DB
        raw_config = get_loader().load_all_namespaces()
    except Exception as e:
        log.error(f"Failed to load configuration from DB: {e}")
        raise RuntimeError("System configuration could not be loaded from database.")
    
    # Determine which environment to use
    selected_env = env_name or os.environ.get("SELECTED_ENV") or raw_config.get("settings", {}).get("active_environment")
    
    config = {}
    if "environments" in raw_config and selected_env in raw_config["environments"]:
        log.info(f"🔧 [CONFIG] Loading environment: {selected_env}")
        config = raw_config["environments"][selected_env]
        # Keep global settings that are NOT inside environments (like telegram)
        for key, value in raw_config.items():
            if key not in ["environments", "active_environment"] and key not in config:
                config[key] = value
    else:
        # Fallback to top-level settings (backward compatibility)
        config = raw_config

    # Overlay sensitive environment variables (Security Priority)
    # Telegram
    if "telegram" not in config:
        config["telegram"] = {}
    
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config["telegram"]["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN")
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram"]["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID")

    # Override structural IPs/Ports if defined in ENV (for containerization flexibility)
    if os.environ.get("TEMPORAL_HOST"):
        if "temporal" not in config: config["temporal"] = {}
        config["temporal"]["host"] = os.environ.get("TEMPORAL_HOST")
    if os.environ.get("TEMPORAL_PORT"):
        if "temporal" not in config: config["temporal"] = {}
        config["temporal"]["port"] = int(os.environ.get("TEMPORAL_PORT"))
        
    # Canonical Qdrant env var: QDRANT_URL (full http://host:port).
    # The legacy host-only var has been retired — see tasks/lessons.md.
    if os.environ.get("QDRANT_URL"):
        if "qdrant" not in config:
            config["qdrant"] = {}
        qdrant_url = os.environ.get("QDRANT_URL")
        config["qdrant"]["url"] = qdrant_url
        # Keep legacy host/port keys populated for code that still reads them.
        try:
            from urllib.parse import urlparse

            parsed = urlparse(qdrant_url)
            if parsed.hostname:
                config["qdrant"]["host"] = parsed.hostname
            if parsed.port:
                config["qdrant"]["port"] = parsed.port
        except Exception:
            pass

    if os.environ.get("REDIS_HOST"):
        if "redis" not in config: config["redis"] = {}
        config["redis"]["host"] = os.environ.get("REDIS_HOST")

    if os.environ.get("LMSTUDIO_HOST"):
        if "lmstudio" not in config: config["lmstudio"] = {}
        config["lmstudio"]["host"] = os.environ.get("LMSTUDIO_HOST")
    if os.environ.get("LMSTUDIO_PORT"):
        if "lmstudio" not in config: config["lmstudio"] = {}
        config["lmstudio"]["port"] = int(os.environ.get("LMSTUDIO_PORT"))

    # Opik (Self-hosted Observability)
    if "opik" in config:
        host = config["opik"].get("host", "localhost")
        port = config["opik"].get("ui_port", 5173)
        # Construct base url for the Opik proxy (Nginx handles /api/ and routes to backend:8080)
        opik_url = f"http://{host}:{port}/api"
        os.environ["OPIK_URL_OVERRIDE"] = opik_url
        os.environ.setdefault("OPIK_PROJECT_NAME", "ai-orchestration")

    return config

