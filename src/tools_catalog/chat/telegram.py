"""
Telegram tool — send/receive messages and files via Telegram.

Two surfaces:
  - start_listener(): wraps TelegramMonitor — polls for messages and submits
    tasks to the scheduler via on_message(). Genesis node only.
  - call_tool(): wraps TelegramNotifier — sends text, files, photos, audio,
    video back to the chat. Used by the worker agent.

The internals of TelegramMonitor and TelegramNotifier are NOT changed.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

from src.plugins.base import Tool, Envelope, ToolContext
from src.control.orchestrator.notifier import TelegramNotifier

log = logging.getLogger(__name__)


class TelegramTool(Tool):
    type = "chat"
    name = "telegram"
    description = "Send and receive messages via Telegram"
    listen = True
    node = "both"

    def initialize(self, config: dict) -> None:
        self.config = config
        self.bot_token = config.get("bot_token", "")
        self.chat_id = config.get("chat_id", "")
        self._notifier: TelegramNotifier = None
        self._monitor_task: asyncio.Task = None

    # -------------------------------------------------------------------------
    # Listener surface — genesis only
    # -------------------------------------------------------------------------

    async def start_listener(self, on_message: Callable[[Envelope], None]) -> None:
        """
        Start polling Telegram for incoming messages.
        Each message becomes an Envelope and is passed to on_message()
        which submits it to the scheduler.

        Wraps TelegramMonitor without modifying its internals.
        """
        if not self.bot_token or not self.chat_id:
            log.error("Telegram tool: bot_token and chat_id required to start listener")
            return

        self._monitor_task = asyncio.create_task(
            self._poll_loop(on_message)
        )
        log.info(f"Telegram listener started (chat_id={self.chat_id})")

    async def stop_listener(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        log.info("Telegram listener stopped")

    async def _poll_loop(self, on_message: Callable[[Envelope], None]) -> None:
        """
        Poll Telegram bot API for updates and forward them to the scheduler.
        Uses the same offset-tracking logic as the existing TelegramMonitor.
        """
        import requests

        api_url = f"https://api.telegram.org/bot{self.bot_token}"
        last_update_id_file = "data/tg_last_update_id.txt"
        os.makedirs("data", exist_ok=True)

        # Load persisted offset to avoid reprocessing old messages
        last_update_id = 0
        if os.path.exists(last_update_id_file):
            try:
                with open(last_update_id_file) as f:
                    last_update_id = int(f.read().strip())
            except Exception:
                pass

        log.info(f"Telegram poll loop started (last_update_id={last_update_id})")

        while True:
            try:
                # Long-poll for updates
                resp = await asyncio.to_thread(
                    requests.get,
                    f"{api_url}/getUpdates",
                    params={"offset": last_update_id + 1, "timeout": 30},
                    timeout=35,
                )
                updates = resp.json().get("result", []) if resp.status_code == 200 else []

                for update in updates:
                    last_update_id = update.get("update_id", 0)
                    # Persist offset immediately
                    try:
                        with open(last_update_id_file, "w") as f:
                            f.write(str(last_update_id))
                    except Exception:
                        pass

                    message = update.get("message", {})
                    if not message:
                        continue

                    msg_text = message.get("text", "").strip()
                    msg_chat_id = str(message.get("chat", {}).get("id", ""))

                    # Only accept messages from the authorised chat
                    if msg_chat_id != self.chat_id:
                        log.warning(f"Rejected message from unauthorised chat {msg_chat_id}")
                        continue

                    if not msg_text:
                        continue

                    # Strip command prefix for /do tasks
                    task_text = msg_text
                    if msg_text.startswith("/do "):
                        task_text = msg_text[4:].strip()
                    elif msg_text.startswith("/"):
                        # Handle built-in commands internally, don't create tasks
                        await self._handle_command(msg_text)
                        continue

                    envelope = Envelope(
                        source=self.name,       # "telegram" (or instance name)
                        task_description=task_text,
                        payload=msg_text,
                        content_type="text/plain",
                        reply_to=self.name,
                        metadata={
                            "chat_id": msg_chat_id,
                            "message_id": message.get("message_id"),
                            "from": message.get("from", {}),
                        },
                        # Scope: agent can use this telegram instance + general tools
                        tool_scope=[self.name, "shell", "filesystem", "web",
                                    "git", "image", "http_client"],
                    )
                    await on_message(envelope)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Telegram poll error: {e} — retrying in 5s")
                await asyncio.sleep(5)

            await asyncio.sleep(1)

    async def _handle_command(self, command: str) -> None:
        """Handle built-in Telegram commands without creating a task."""
        notifier = self._get_notifier()
        if command == "/start":
            notifier.send_message(
                "👋 *Welcome to AI Orchestrator*\n"
                "Send me any task description to start execution.\n"
                "Use /do <task> or just type your task directly."
            )
        elif command == "/status":
            notifier.send_message("📊 *System Status*: Online\nGenesis Node is ready.")
        else:
            notifier.send_message(f"❓ Unknown command: `{command}`")

    # -------------------------------------------------------------------------
    # Agent action surface — worker
    # -------------------------------------------------------------------------

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "chat_send",
                    "description": (
                        "Send a text message to the Telegram chat. "
                        "Use to deliver results, progress updates, or replies."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Message text. Supports Telegram Markdown.",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_file",
                    "description": (
                        "Send a file from the workspace to the Telegram chat. "
                        "Images are sent inline. Other files as documents."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to workspace",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Optional caption for the file",
                                "default": "",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        notifier = self._get_notifier()
        if tool_name == "chat_send":
            ok = notifier.send_message(args["text"])
            return "OK: Message sent" if ok else "ERROR: Failed to send message"
        if tool_name == "send_file":
            return await self._send_file(notifier, ctx.workspace_dir, **args)
        return f"ERROR: Unknown tool '{tool_name}'"

    async def _send_file(self, notifier: TelegramNotifier, workspace_dir: str,
                         path: str, caption: str = "") -> str:
        import os
        import mimetypes
        full_path = os.path.join(workspace_dir, path)
        if not os.path.exists(full_path):
            return f"ERROR: File not found: {path}"

        mime, _ = mimetypes.guess_type(full_path)
        mime = mime or "application/octet-stream"

        if mime.startswith("image/"):
            ok = notifier.send_photo(full_path, caption=caption)
        elif mime.startswith("video/"):
            ok = notifier.send_video(full_path, caption=caption)
        elif mime.startswith("audio/"):
            ok = notifier.send_audio(full_path, caption=caption)
        else:
            ok = notifier.send_document(full_path, caption=caption)

        return f"OK: Sent {path}" if ok else f"ERROR: Failed to send {path}"

    # -------------------------------------------------------------------------
    # Result delivery — called by scheduler after task completes
    # -------------------------------------------------------------------------

    async def deliver_result(self, envelope: Envelope, result: str,
                             artifacts: list) -> None:
        """Send the agent's result back to the Telegram chat."""
        notifier = self._get_notifier()

        # Truncate long results to Telegram's 4096-char limit
        if len(result) > 4000:
            result = result[:4000] + "\n... _(truncated)_"

        notifier.send_message(f"✅ *Task Complete*\n\n{result}")

        # Send any artifact files
        for artifact in artifacts:
            file_path = artifact.get("path", "")
            filename = artifact.get("filename", "")
            if file_path and os.path.exists(file_path):
                mime = artifact.get("mime_type", "application/octet-stream")
                caption = filename
                if mime.startswith("image/"):
                    notifier.send_photo(file_path, caption=caption)
                elif mime.startswith("video/"):
                    notifier.send_video(file_path, caption=caption)
                elif mime.startswith("audio/"):
                    notifier.send_audio(file_path, caption=caption)
                else:
                    notifier.send_document(file_path, caption=caption)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_notifier(self) -> TelegramNotifier:
        """Lazily instantiate TelegramNotifier (avoids import at load time)."""
        if self._notifier is None:
            self._notifier = TelegramNotifier()
        return self._notifier


tool_class = TelegramTool
