import time
import requests
from src.config import load_settings


class TelegramNotifier:
    def __init__(self):
        self.config = load_settings()
        self.telegram_config = self.config.get("telegram", {})
        self.bot_token = self.telegram_config.get("bot_token")
        self.chat_id = self.telegram_config.get("chat_id")
        self.enabled = bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, retries: int = 2) -> bool:
        if not self.enabled:
            return False

        # Telegram message limit is 4096 chars
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        for attempt in range(retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=15)
                if response.status_code == 200:
                    return True
                # If Markdown parsing fails, retry without parse_mode
                if response.status_code == 400 and attempt == 0:
                    payload.pop("parse_mode", None)
                    continue
            except requests.exceptions.Timeout:
                if attempt < retries:
                    time.sleep(1)
                    continue
                print(f"Telegram notification timed out after {retries + 1} attempts")
                return False
            except Exception as e:
                print(f"Failed to send Telegram notification: {e}")
                return False
        return False
