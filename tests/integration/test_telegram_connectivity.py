import os
import pytest
import requests
from dotenv import load_dotenv
from src.genesis.orchestrator.notifier import TelegramNotifier

@pytest.fixture(autouse=True)
def setup_env():
    """Ensure .env is loaded for connectivity tests."""
    load_dotenv(override=True)

# Determine if we should run live tests based on credentials
HAS_TELEGRAM_CREDS = bool(os.environ.get("TELEGRAM_BOT_TOKEN")) and bool(os.environ.get("TELEGRAM_CHAT_ID"))
skip_msg = "Skipping live Telegram tests due to missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"

@pytest.mark.skipif(not HAS_TELEGRAM_CREDS, reason=skip_msg)
def test_telegram_config_presence():
    """Verify that Telegram environment variables are present and formatted correctly."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    assert token is not None, "TELEGRAM_BOT_TOKEN is missing from environment"
    assert chat_id is not None, "TELEGRAM_CHAT_ID is missing from environment"
    assert ":" in token, "TELEGRAM_BOT_TOKEN format is invalid (missing ':')"
    # Chat IDs can be negative (groups) or positive (users)
    assert chat_id.lstrip('-').isdigit(), f"TELEGRAM_CHAT_ID should be numeric, got {chat_id}"

@pytest.mark.skipif(not HAS_TELEGRAM_CREDS, reason=skip_msg)
def test_telegram_api_connectivity():
    """Verify the Bot Token is valid with the Telegram API."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    response = requests.get(url, timeout=10)
    assert response.status_code == 200, f"Telegram API returned {response.status_code}: {response.text}"
    
    data = response.json()
    assert data.get("ok") is True
    assert "username" in data.get("result", {})

@pytest.mark.skipif(not HAS_TELEGRAM_CREDS, reason=skip_msg)
def test_telegram_notifier_integration():
    """Verify that the internal TelegramNotifier class can send a message."""
    notifier = TelegramNotifier()
    assert notifier.enabled is True, "TelegramNotifier should be enabled with valid config"
    
    # We send a diagnostic message
    success = notifier.send_message("🛠 *Automated Connectivity Test*\nIntegration verified.")
    assert success is True, "Failed to send integration test message"
