import os
import yaml
from dotenv import load_dotenv

# Ensure environment variables are loaded from .env
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(project_root, ".env"))

def load_settings():
    """
    Centralized configuration loader.
    Merges static config from config/settings.yaml with sensitive
    environment variables loaded from .env or os.environ.
    """
    settings_path = os.path.join(project_root, "config/settings.yaml")
    config = {}
    
    # Load structural configuration
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            config = yaml.safe_load(f) or {}

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
        
    if os.environ.get("QDRANT_HOST"):
        if "qdrant" not in config: config["qdrant"] = {}
        config["qdrant"]["host"] = os.environ.get("QDRANT_HOST")

    return config
