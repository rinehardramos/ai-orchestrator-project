import os
import sys
import time
import asyncio
import requests
import json
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.cnc.analyzer.task_analyzer import TaskAnalyzer, TaskRequirement, AnalyzerResult
from src.cnc.orchestrator.scheduler import TaskScheduler
from src.cnc.orchestrator.notifier import TelegramNotifier
from src.config import load_settings

import logging

# Configure logging — use RotatingFileHandler to protect SD card
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

# Only our loggers go to file; silence noisy libraries
logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')

_file_handler = RotatingFileHandler("logs/telegram_monitor.log", maxBytes=512_000, backupCount=1)
_file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logger = logging.getLogger("TelegramMonitor")
logger.setLevel(logging.INFO)
logger.addHandler(_file_handler)
logger.addHandler(_stream_handler)

class TelegramMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id_file = "data/tg_last_update_id.txt"
        os.makedirs("data", exist_ok=True)
        self.last_update_id = self._load_last_update_id()
        self.analyzer = TaskAnalyzer()
        self.notifier = TelegramNotifier()
        self.scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
        self.is_running = True

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

    async def _process_message(self, message: Dict[str, Any]):
        msg_text = message.get("text", "")
        msg_chat_id = str(message.get("chat", {}).get("id", ""))
        
        logger.debug(f"Incoming message from {msg_chat_id}: {msg_text}")

        if msg_chat_id != self.chat_id:
            logger.warning(f"⚠️ Unauthorized chat ID: {msg_chat_id}")
            return

        if not msg_text:
            return

        # Immediate acknowledgement
        self._send_chat_action("typing")

        if msg_text.startswith("/"):
            await self._handle_command(msg_text)
        else:
            await self._handle_task(msg_text)

    def _send_chat_action(self, action: str):
        """Sends a chat action like 'typing' to the user."""
        url = f"{self.api_url}/sendChatAction"
        payload = {"chat_id": self.chat_id, "action": action}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send chat action: {e}")

    async def _handle_command(self, command: str):
        logger.debug(f"Handling command: {command}")
        
        if command == "/start":
            self.notifier.send_message("👋 *Welcome to Gemini AI Orchestrator*\nSend me any task description to start execution.")
        elif command == "/status":
            self.notifier.send_message("📊 *System Status*: Online\nGenesis Node is ready and listening.")
        elif command.startswith("/do "):
            task_text = command[4:].strip()
            if task_text:
                await self._handle_task(task_text)
            else:
                self.notifier.send_message("⚠️ Please provide a task description after /do")
        else:
            self.notifier.send_message(f"❓ Unknown command: {command}")

    async def _handle_task(self, statement: str):
        logger.info(f"Task received: {statement[:80]}")
        # 0. Immediate Receipt Confirmation
        self.notifier.send_message(f"📥 *Received*: \"{statement}\"\n_Analyzing requirements..._")
        
        try:
            # 1. Analyze task
            logger.debug(f"Parsing statement: {statement}")
            task_req = await self.analyzer.parse_statement(statement)
            logger.debug(f"Task requirements: {task_req}")
            self._send_chat_action("typing") 
            
            logger.debug(f"Analyzing requirements...")
            result = self.analyzer.analyze(task_req)
            # Telegram mode always uses existing infrastructure (headless — no Pulumi provisioning)
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

            # 2. Submit task
            task_id = await self.scheduler.submit_task(statement, result.model_dump())
            
            if task_id.startswith("QUEUED_OFFLINE"):
                logger.info(f"Offline Mode detected for task {task_id}")
                self.notifier.send_message(f"📴 Task queued offline. ID: `{task_id}`")
            else:
                logger.info(f"Task successfully registered: {task_id}")
                self.notifier.send_message(f"✅ Task Registered: `{task_id}`\nWaiting for completion...")
                
                # 3. Monitor status (background)
                asyncio.create_task(self._wait_for_task(task_id))

        except Exception as e:
            logger.exception("Error during task handling")
            self.notifier.send_message(f"❌ *Error during analysis*: {e}")

    async def _wait_for_task(self, task_id: str):
        try:
            final_status = await self.scheduler.wait_for_completion(task_id)
        except Exception as e:
            logger.exception(f"Error monitoring task {task_id}")
            self.notifier.send_message(f"❌ *Error monitoring task {task_id}*: {e}")

    async def start(self):
        logger.info(f"🤖 Telegram Monitor started. Listening for instructions... (PID: {os.getpid()})")
        logger.info(f"🐍 Python Executable: {sys.executable}")
        
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
