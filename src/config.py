import os
import yaml
from dotenv import load_dotenv

# Ensure environment variables are loaded from .env
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(project_root, ".env"))

def load_settings(env_name: str = None):
    """
    Centralized configuration loader.
    Merges static config from config/settings.yaml with sensitive
    environment variables loaded from .env or os.environ.
    
    Supports multi-environment configuration if 'environments' key exists.
    """
    settings_path = os.path.join(project_root, "config/settings.yaml")
    raw_config = {}
    
    # Load structural configuration
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            raw_config = yaml.safe_load(f) or {}

    # Determine which environment to use
    selected_env = env_name or os.environ.get("SELECTED_ENV") or raw_config.get("active_environment")
    
    config = {}
    if "environments" in raw_config and selected_env in raw_config["environments"]:
        print(f"🔧 [CONFIG] Loading environment: {selected_env}")
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
        
    if os.environ.get("QDRANT_HOST"):
        if "qdrant" not in config: config["qdrant"] = {}
        config["qdrant"]["host"] = os.environ.get("QDRANT_HOST")

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
