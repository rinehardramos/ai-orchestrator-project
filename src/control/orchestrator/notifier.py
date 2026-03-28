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

    def send_photo(self, image_bytes: bytes, caption: str = "") -> bool:
        """Send a photo to the Telegram chat."""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."
        try:
            response = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption},
                files={"photo": ("image.png", image_bytes, "image/png")},
                timeout=30,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send Telegram photo: {e}")
            return False

    def send_document(self, file_bytes: bytes, filename: str, caption: str = "") -> bool:
        """Send a file/document to the Telegram chat."""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "application/octet-stream"
            response = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption},
                files={"document": (filename, file_bytes, mime_type)},
                timeout=30,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send Telegram document: {e}")
            return False

    def send_video(self, video_bytes: bytes, filename: str, caption: str = "") -> bool:
        """Send a video to the Telegram chat (renders inline)."""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendVideo"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "video/mp4"
            response = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption, "supports_streaming": True},
                files={"video": (filename, video_bytes, mime_type)},
                timeout=60,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send Telegram video: {e}")
            return False

    def send_audio(self, audio_bytes: bytes, filename: str, caption: str = "") -> bool:
        """Send an audio file to the Telegram chat (renders as playable audio)."""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendAudio"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "audio/mpeg"
            response = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption},
                files={"audio": (filename, audio_bytes, mime_type)},
                timeout=60,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send Telegram audio: {e}")
            return False
