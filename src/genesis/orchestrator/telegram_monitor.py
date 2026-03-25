import os
import sys
import time
import asyncio
import requests
import json
import base64
from typing import Optional, Dict, Any
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.genesis.orchestrator.notifier import TelegramNotifier
from src.genesis.diagnostics.diagnostic_agent import DiagnosticAgent
from src.genesis.diagnostics.models import ServiceType
from src.config import load_settings

import logging

from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')

_file_handler = RotatingFileHandler("logs/telegram_monitor.log", maxBytes=512_000, backupCount=1)
_file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logger = logging.getLogger("TelegramMonitor")
logger.setLevel(logging.INFO)
logger.addHandler(_file_handler)
logger.addHandler(_stream_handler)

for _name in ("TaskScheduler", "MultiAgentGraph", "Worker", "DiagnosticAgent"):
    _l = logging.getLogger(_name)
    _l.setLevel(logging.INFO)
    _l.addHandler(_file_handler)
    _l.addHandler(_stream_handler)
    _l.propagate = False


class TelegramMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id_file = "data/tg_last_update_id.txt"
        os.makedirs("data", exist_ok=True)
        self.last_update_id = self._load_last_update_id()
        
        self.notifier = TelegramNotifier()
        self.config = load_settings()
        
        self._diagnostic_agent = None
        
        self._scheduler = None
        self._analyzer = None
        
        self.is_running = True

    @property
    def diagnostic_agent(self) -> DiagnosticAgent:
        if self._diagnostic_agent is None:
            self._diagnostic_agent = DiagnosticAgent(self.config)
        return self._diagnostic_agent

    @property
    def scheduler(self):
        if self._scheduler is None:
            from src.genesis.orchestrator.scheduler import TaskScheduler
            self._scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
        return self._scheduler

    @property
    def analyzer(self):
        if self._analyzer is None:
            from src.genesis.analyzer.task_analyzer import TaskAnalyzer
            self._analyzer = TaskAnalyzer()
        return self._analyzer

    def _load_last_update_id(self) -> int:
        if os.path.exists(self.last_update_id_file):
            try:
                with open(self.last_update_id_file, "r") as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return 0

    def _save_last_update_id(self, update_id: int):
        try:
            with open(self.last_update_id_file, "w") as f:
                f.write(str(update_id))
        except Exception as e:
            logger.error(f"Failed to save last_update_id: {e}")

    def _get_updates(self):
        url = f"{self.api_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 30}
        try:
            response = requests.get(url, params=params, timeout=35)
            if response.status_code == 200:
                return response.json().get("result", [])
        except Exception as e:
            logger.error(f"Error getting updates: {e}")
        return []

    def _get_file_path(self, file_id: str) -> Optional[str]:
        url = f"{self.api_url}/getFile?file_id={file_id}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                result = response.json().get("result", {})
                return result.get("file_path")
        except Exception as e:
            logger.error(f"Error getting file path: {e}")
        return None

    def _download_file(self, file_id: str, max_size_mb: int = 25) -> Optional[bytes]:
        file_path = self._get_file_path(file_id)
        if not file_path:
            logger.error(f"Could not get file path for file_id: {file_id}")
            return None
        
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                content = response.content
                size_mb = len(content) / (1024 * 1024)
                if size_mb > max_size_mb:
                    logger.warning(f"File too large: {size_mb:.1f}MB > {max_size_mb}MB")
                    return None
                return content
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
        return None

    async def _process_message(self, message: Dict[str, Any]):
        msg_chat_id = str(message.get("chat", {}).get("id", ""))
        
        logger.debug(f"Incoming message from {msg_chat_id}")

        if msg_chat_id != self.chat_id:
            logger.warning(f"⚠️ Unauthorized chat ID: {msg_chat_id}")
            return

        self._send_chat_action("typing")

        msg_text = message.get("text", "")
        
        if msg_text:
            if msg_text.startswith("/"):
                await self._handle_command(msg_text)
            else:
                await self._handle_task(msg_text)
            return
        
        if "voice" in message:
            await self._handle_voice(message)
            return
        
        if "photo" in message:
            await self._handle_photo(message)
            return
        
        if "audio" in message:
            await self._handle_audio(message)
            return
        
        logger.debug(f"Unsupported message type from {msg_chat_id}")

    async def _handle_voice(self, message: Dict[str, Any]):
        logger.info("Processing voice message")
        voice = message.get("voice", {})
        duration = voice.get("duration", 0)
        
        self.notifier.send_message("🎤 *Transcribing voice message*...")
        
        audio_bytes = await asyncio.to_thread(self._download_file, voice.get("file_id"))
        
        if not audio_bytes:
            self.notifier.send_message("❌ Failed to download voice message")
            return
        
        try:
            envelope = {
                "source": "telegram",
                "task_description": "Transcribe this voice message and respond to the user's request",
                "payload": base64.b64encode(audio_bytes).decode(),
                "content_type": voice.get("mime_type", "audio/ogg"),
                "metadata": {
                    "duration": duration,
                    "message_type": "voice"
                },
                "tool_scope": ["telegram", "transcribe_audio", "shell", "web", "filesystem"]
            }
            
            task_id = await self._submit_media_envelope(envelope)
            
            if task_id:
                self.notifier.send_message(f"✅ Processing voice message...\nTask: `{task_id}`")
            else:
                self.notifier.send_message("❌ Failed to submit voice message for processing")
                
        except Exception as e:
            logger.exception("Error handling voice message")
            self.notifier.send_message(f"❌ Error processing voice: `{str(e)[:100]}`")

    async def _handle_photo(self, message: Dict[str, Any]):
        logger.info("Processing photo message")
        photos = message.get("photo", [])
        
        if not photos:
            self.notifier.send_message("❌ No photo found in message")
            return
        
        photo = photos[-1]
        caption = message.get("caption", "")
        
        self.notifier.send_message("📷 *Analyzing image*...")
        
        image_bytes = await asyncio.to_thread(self._download_file, photo.get("file_id"))
        
        if not image_bytes:
            self.notifier.send_message("❌ Failed to download image")
            return
        
        try:
            task_desc = caption if caption else "Analyze this image and help the user with their request"
            
            envelope = {
                "source": "telegram",
                "task_description": task_desc,
                "payload": base64.b64encode(image_bytes).decode(),
                "content_type": "image/jpeg",
                "metadata": {
                    "has_caption": bool(caption),
                    "message_type": "photo"
                },
                "tool_scope": ["telegram", "analyze_image", "transcribe_audio", "shell", "web", "filesystem"]
            }
            
            task_id = await self._submit_media_envelope(envelope)
            
            if task_id:
                self.notifier.send_message(f"✅ Processing image...\nTask: `{task_id}`")
            else:
                self.notifier.send_message("❌ Failed to submit image for processing")
                
        except Exception as e:
            logger.exception("Error handling photo")
            self.notifier.send_message(f"❌ Error processing image: `{str(e)[:100]}`")

    async def _handle_audio(self, message: Dict[str, Any]):
        logger.info("Processing audio file")
        audio = message.get("audio", {})
        
        self.notifier.send_message("🎵 *Processing audio file*...")
        
        audio_bytes = await asyncio.to_thread(self._download_file, audio.get("file_id"))
        
        if not audio_bytes:
            self.notifier.send_message("❌ Failed to download audio file")
            return
        
        try:
            envelope = {
                "source": "telegram",
                "task_description": "Process this audio file and respond to the user's request",
                "payload": base64.b64encode(audio_bytes).decode(),
                "content_type": audio.get("mime_type", "audio/mpeg"),
                "metadata": {
                    "filename": audio.get("file_name", "audio.mp3"),
                    "duration": audio.get("duration", 0),
                    "message_type": "audio"
                },
                "tool_scope": ["telegram", "transcribe_audio", "analyze_image", "shell", "web", "filesystem"]
            }
            
            task_id = await self._submit_media_envelope(envelope)
            
            if task_id:
                self.notifier.send_message(f"✅ Processing audio...\nTask: `{task_id}`")
            else:
                self.notifier.send_message("❌ Failed to submit audio for processing")
                
        except Exception as e:
            logger.exception("Error handling audio")
            self.notifier.send_message(f"❌ Error processing audio: `{str(e)[:100]}`")

    async def _submit_media_envelope(self, envelope: Dict[str, Any]) -> Optional[str]:
        try:
            task_input = json.dumps({
                "envelope": envelope
            })
            
            analysis_result = {
                "llm_model_id": "auto",
                "infrastructure_id": "existing_server",
                "infra_details": {"provider": "existing_infra", "type": "container"},
                "estimated_cost": 0.01
            }
            
            task_id = await self.scheduler.submit_task(task_input, analysis_result, source="telegram")
            return task_id
            
        except Exception as e:
            logger.exception(f"Error submitting media envelope: {e}")
            return None

    def _send_chat_action(self, action: str):
        url = f"{self.api_url}/sendChatAction"
        payload = {"chat_id": self.chat_id, "action": action}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send chat action: {e}")

    async def _handle_command(self, command: str):
        logger.debug(f"Handling command: {command}")
        
        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1:] if len(cmd_parts) > 1 else []
        
        if cmd == "/start":
            self.notifier.send_message(
                "👋 *Welcome to AI Orchestrator*\n\n"
                "Available commands:\n"
                "/diagnose - Run system health check\n"
                "/fix - Diagnose and auto-fix issues\n"
                "/model [name] - View/set diagnostic model\n"
                "/status - Show system status\n\n"
                "Task submission:\n"
                "/do <task> - Submit a task for execution\n"
                "Or just type your task directly.\n\n"
                "Media support:\n"
                "🎤 Voice messages - Transcribed and processed\n"
                "📷 Photos - Analyzed with vision AI\n"
                "🎵 Audio files - Transcribed and processed"
            )
        
        elif cmd == "/status":
            await self._cmd_status()
        
        elif cmd == "/diagnose":
            await self._cmd_diagnose(auto_fix=False)
        
        elif cmd == "/fix":
            dry_run = "--dry-run" in args
            await self._cmd_diagnose(auto_fix=True, dry_run=dry_run)
        
        elif cmd == "/model":
            model_name = args[0] if args else None
            await self._cmd_model(model_name)
        
        elif command.startswith("/do "):
            task_text = command[4:].strip()
            if task_text:
                await self._handle_task(task_text)
            else:
                self.notifier.send_message("⚠️ Please provide a task description after /do")
        
        else:
            self.notifier.send_message(f"❓ Unknown command: `{cmd}`\n\nUse /start to see available commands.")

    async def _cmd_status(self):
        self.notifier.send_message("🔍 Checking system status...")
        
        try:
            report = self.diagnostic_agent.diagnose_only()
            summary = report.to_telegram_summary()
            self.notifier.send_message(summary)
        except Exception as e:
            logger.exception("Error during status check")
            self.notifier.send_message(f"❌ *Status Check Failed*\n\nError: `{str(e)[:200]}`")

    async def _cmd_diagnose(self, auto_fix: bool = False, dry_run: bool = False):
        if auto_fix:
            if dry_run:
                self.notifier.send_message("🔧 *Starting diagnosis (dry-run mode)*...\n_Planning without executing actions._")
            else:
                self.notifier.send_message("🔧 *Starting diagnosis and auto-fix*...\n_This may take a minute._")
        else:
            self.notifier.send_message("🔍 *Running system diagnosis*...")
        
        try:
            if auto_fix:
                report = await asyncio.to_thread(
                    self.diagnostic_agent.diagnose_and_fix,
                    None,
                    dry_run
                )
            else:
                report = await asyncio.to_thread(self.diagnostic_agent.diagnose_only)
            
            summary = report.to_telegram_summary()
            self.notifier.send_message(summary)
            
        except Exception as e:
            logger.exception("Error during diagnosis")
            self.notifier.send_message(f"❌ *Diagnosis Failed*\n\nError: `{str(e)[:200]}`")

    async def _cmd_model(self, model_name: Optional[str]):
        current_model = self.diagnostic_agent.get_model()
        
        if model_name:
            self.diagnostic_agent.set_model(model_name)
            self.notifier.send_message(
                f"✅ *Diagnostic Model Updated*\n\n"
                f"Previous: `{current_model}`\n"
                f"New: `{model_name}`"
            )
        else:
            diag_config = self.config.get("genesis", {}).get("diagnostic", {})
            fallback = diag_config.get("fallback_model", "none")
            
            self.notifier.send_message(
                f"📊 *Current Diagnostic Model*\n\n"
                f"Model: `{current_model}`\n"
                f"Fallback: `{fallback}`\n\n"
                f"Use `/model <name>` to change.\n"
                f"Examples:\n"
                f"• `/model anthropic/claude-3.5-sonnet`\n"
                f"• `/model openai/gpt-4o`\n"
                f"• `/model google/gemini-2.5-pro`"
            )

    async def _handle_task(self, statement: str):
        logger.info(f"Task received: {statement[:80]}")
        
        self.notifier.send_message(f"📥 *Received*: \"{statement}\"\n_Analyzing requirements..._")
        
        try:
            logger.debug(f"Parsing statement: {statement}")
            task_req = await self.analyzer.parse_statement(statement)
            logger.debug(f"Task requirements: {task_req}")
            self._send_chat_action("typing")
            
            logger.debug(f"Analyzing requirements...")
            result = self.analyzer.analyze(task_req)
            result.infrastructure_id = "existing_server"
            result.infra_details = {"provider": "existing_infra", "type": "container", "startup_time_sec": 1}
            logger.debug(f"Analyzer result: {result}")
            
            summary = (
                f"📝 *Execution Plan*\n"
                f"- *Model*: `{result.llm_model_id}`\n"
                f"- *Infra*: `{result.infrastructure_id}`\n"
                f"- *Cost*: `${result.estimated_cost:.4f}`\n\n"
                f"🚀 Delegating to Control Plane..."
            )
            self.notifier.send_message(summary)

            task_id = await self.scheduler.submit_task(statement, result.model_dump(), source="telegram")
            
            if task_id.startswith("QUEUED_OFFLINE"):
                logger.info(f"Offline Mode detected for task {task_id}")
                self.notifier.send_message(f"📴 Task queued offline. ID: `{task_id}`")
            else:
                logger.info(f"Task successfully registered: {task_id}")
                self.notifier.send_message(f"✅ Task Registered: `{task_id}`\nWaiting for completion...")
                
                asyncio.create_task(self._wait_for_task(task_id))

        except Exception as e:
            logger.exception("Error during task handling")
            
            if "temporal" in str(e).lower() or "connection" in str(e).lower():
                self.notifier.send_message(
                    f"❌ *Connection Error*\n\n"
                    f"Could not connect to Control Plane.\n"
                    f"Task queued offline.\n\n"
                    f"Use `/fix` to diagnose connectivity issues."
                )
            else:
                self.notifier.send_message(f"❌ *Error during analysis*: `{str(e)[:200]}`")

    async def _wait_for_task(self, task_id: str):
        try:
            final_status = await self.scheduler.wait_for_completion(task_id)
        except Exception as e:
            logger.exception(f"Error monitoring task {task_id}")
            self.notifier.send_message(f"❌ *Error monitoring task {task_id}*: `{str(e)[:200]}`")

    async def start(self):
        logger.info(f"🤖 Telegram Monitor started. Listening for instructions... (PID: {os.getpid()})")
        logger.info(f"🐍 Python Executable: {sys.executable}")
        logger.info(f"📊 Diagnostic Model: {self.diagnostic_agent.get_model()}")
        
        while self.is_running:
            updates = await asyncio.to_thread(self._get_updates)
            
            for update in updates:
                self.last_update_id = update.get("update_id", 0)
                self._save_last_update_id(self.last_update_id)
                if "message" in update:
                    await self._process_message(update["message"])
            await asyncio.sleep(1)


async def main():
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        return

    monitor = TelegramMonitor(bot_token, chat_id)
    await monitor.start()

if __name__ == "__main__":
    asyncio.run(main())
