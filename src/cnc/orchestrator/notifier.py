import os
import requests
from src.config import load_settings

class TelegramNotifier:
    def __init__(self):
        self.config = load_settings()
        self.telegram_config = self.config.get("telegram", {})
        self.bot_token = self.telegram_config.get("bot_token")
        self.chat_id = self.telegram_config.get("chat_id")
        self.enabled = bool(self.bot_token and self.chat_id)

    def send_message(self, text: str):
        if not self.enabled:
            return False
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send Telegram notification: {e}")
            return False
