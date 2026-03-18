import pytest
from unittest.mock import patch, MagicMock
from src.cnc.orchestrator.notifier import TelegramNotifier

@patch("src.cnc.orchestrator.notifier.load_settings")
@patch("src.cnc.orchestrator.notifier.requests.post")
def test_telegram_notifier_success(mock_post, mock_load_settings):
    # Setup mock configuration
    mock_load_settings.return_value = {
        "telegram": {
            "bot_token": "fake_token",
            "chat_id": "12345"
        }
    }
    
    # Setup mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    notifier = TelegramNotifier()
    assert notifier.enabled is True

    result = notifier.send_message("Test message")
    
    assert result is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "fake_token" in args[0]
    assert kwargs["json"]["chat_id"] == "12345"
    assert kwargs["json"]["text"] == "Test message"

@patch("src.cnc.orchestrator.notifier.load_settings")
def test_telegram_notifier_disabled(mock_load_settings):
    # Setup mock configuration with missing telegram
    mock_load_settings.return_value = {}

    notifier = TelegramNotifier()
    assert notifier.enabled is False

    result = notifier.send_message("Test message")
    assert result is False
