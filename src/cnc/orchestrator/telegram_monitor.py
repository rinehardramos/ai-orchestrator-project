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
            print(f"Failed to save last_update_id: {e}")

    def _get_updates(self):
        url = f"{self.api_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 30}
        try:
            response = requests.get(url, params=params, timeout=35)
            if response.status_code == 200:
                return response.json().get("result", [])
        except Exception as e:
            print(f"Error getting updates: {e}")
        return []

    async def _process_message(self, message: Dict[str, Any]):
        msg_text = message.get("text", "")
        msg_chat_id = str(message.get("chat", {}).get("id", ""))
        
        print(f"📩 Incoming message from {msg_chat_id}: {msg_text}")
        sys.stdout.flush()

        if msg_chat_id != self.chat_id:
            print(f"⚠️ Unauthorized chat ID: {msg_chat_id}")
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
            print(f"Failed to send chat action: {e}")

    async def _handle_command(self, command: str):
        print(f"🛠 Handling command: {command}")
        sys.stdout.flush()
        
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
        print(f"🚀 Handling task: {statement}")
        sys.stdout.flush()
        # 0. Immediate Receipt Confirmation
        self.notifier.send_message(f"📥 *Received*: \"{statement}\"\n_Analyzing requirements..._")
        
        try:
            # 1. Analyze task
            task_req = await self.analyzer.parse_statement(statement)
            self._send_chat_action("typing") # Keep typing indicator alive
            
            result = self.analyzer.analyze(task_req)
            
            # For simplicity, we use the existing infra if possible or assume local_server_docker for now
            # In a full impl, we'd call provision_worker here too.
            # But the prompt says "send the instructions to the control plane".
            # The control plane (Temporal) can handle the execution.
            
            summary = (
                f"📝 *Execution Plan*\n"
                f"- *Model*: `{result.llm_model_id}`\n"
                f"- *Infra*: `{result.infrastructure_id}`\n"
                f"- *Cost*: `${result.estimated_cost:.4f}`\n\n"
                f"🚀 Delegating to Control Plane..."
            )
            self.notifier.send_message(summary)

            # 2. Submit task
            # Using model_dump() for Pydantic V2 compatibility
            task_id = await self.scheduler.submit_task(statement, result.model_dump())
            
            if task_id.startswith("QUEUED_OFFLINE"):
                self.notifier.send_message(f"📴 Task queued offline. ID: `{task_id}`")
            else:
                self.notifier.send_message(f"✅ Task Registered: `{task_id}`\nWaiting for completion...")
                
                # 3. Monitor status (background)
                asyncio.create_task(self._wait_for_task(task_id))

        except Exception as e:
            self.notifier.send_message(f"❌ *Error during analysis*: {e}")

    async def _wait_for_task(self, task_id: str):
        try:
            final_status = await self.scheduler.wait_for_completion(task_id)
            # Notifier is called inside scheduler.wait_for_completion for success/failure
        except Exception as e:
            self.notifier.send_message(f"❌ *Error monitoring task {task_id}*: {e}")

    async def start(self):
        print(f"🤖 Telegram Monitor started. Listening for instructions... (PID: {os.getpid()})")
        print(f"🐍 Python Executable: {sys.executable}")
        print(f"📚 sys.path: {sys.path}")
        sys.stdout.flush()
        
        # Diagnostic file logging
        log_file = "logs/telegram_monitor_debug.log"
        os.makedirs("logs", exist_ok=True)
        
        with open(log_file, "a") as f:
            f.write(f"\n--- Monitor Started at {time.ctime()} ---\n")

        while self.is_running:
            updates = await asyncio.to_thread(self._get_updates)
            if updates:
                with open(log_file, "a") as f:
                    f.write(f"Received {len(updates)} updates at {time.ctime()}\n")
            
            for update in updates:
                self.last_update_id = update.get("update_id", 0)
                self._save_last_update_id(self.last_update_id) # Persistent tracking
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
