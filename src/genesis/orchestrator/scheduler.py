import base64
import boto3
import uuid
import time
import asyncio
import os
import socket
import sqlite3
import json
import logging
from typing import Dict, Any
from temporalio.client import Client

# Configure logging
logger = logging.getLogger("TaskScheduler")

# Local imports
try:
    from src.genesis.orchestrator.notifier import TelegramNotifier
except ImportError:
    TelegramNotifier = None

from src.config import load_settings

class TaskScheduler:
    def __init__(self, queue_url: str, table_name: str, region: str = "us-east-1"):
        self.queue_url = queue_url
        self.config = load_settings()
        
        # Caching for pre-flight
        self.preflight_cache = {}
        
        # Offline Queue DB Initialization
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
        os.makedirs(data_dir, exist_ok=True)
        self.offline_db_path = os.path.join(data_dir, "offline_queue.db")
        self._init_offline_db()
        
        # Notifier setup
        self.notifier = TelegramNotifier() if TelegramNotifier else None

        if self.queue_url != "dummy-temporal-queue":
            self.sqs = boto3.client('sqs', region_name=region)
            self.dynamodb = boto3.resource('dynamodb', region_name=region)
            self.table = self.dynamodb.Table(table_name)
        else:
            self.sqs = None
            self.dynamodb = None
            self.table = None

    def _init_offline_db(self):
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute("PRAGMA journal_mode=WAL")  # Reduce disk writes on SD card
        c.execute('''CREATE TABLE IF NOT EXISTS offline_tasks
                     (task_id TEXT PRIMARY KEY, description TEXT, metadata TEXT, status TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS task_history
                     (task_id TEXT PRIMARY KEY, description TEXT, submitted_at REAL, status TEXT)''')
        conn.commit()
        conn.close()

    def _save_task_offline(self, task_id: str, description: str, metadata: Dict[str, Any]):
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        meta_str = json.dumps(metadata) if metadata else "{}"
        c.execute("INSERT INTO offline_tasks (task_id, description, metadata, status) VALUES (?, ?, ?, ?)",
                  (task_id, description, meta_str, 'QUEUED'))
        conn.commit()
        conn.close()
        logger.info(f"📴 [OFFLINE] Task {task_id} queued locally. It will be flushed when network is restored.")
        if self.notifier:
            self.notifier.send_message(f"📴 *Offline Mode*: Task {task_id} queued locally.")

    def _record_task(self, task_id: str, description: str, source: str = "cli"):
        """Record a submitted task in the local history table."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        # Add source column on first use (backward-compatible)
        try:
            c.execute("ALTER TABLE task_history ADD COLUMN source TEXT DEFAULT 'cli'")
            conn.commit()
        except Exception:
            pass
        c.execute(
            "INSERT OR REPLACE INTO task_history (task_id, description, submitted_at, status, source) VALUES (?, ?, ?, ?, ?)",
            (task_id, description, time.time(), "SUBMITTED", source)
        )
        conn.commit()
        conn.close()

    def _get_task_source(self, task_id: str) -> str:
        """Retrieve the source that submitted this task."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT source FROM task_history WHERE task_id=?", (task_id,))
            row = c.fetchone()
            return row[0] if row and row[0] else "cli"
        except Exception:
            return "cli"
        finally:
            conn.close()

    def _update_task_status(self, task_id: str, status: str):
        """Update the status of a task in the local history table."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute("UPDATE task_history SET status=? WHERE task_id=?", (status, task_id))
        conn.commit()
        conn.close()

    def _get_task_description(self, task_id: str) -> str:
        """Read a task's description from the local history table."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute("SELECT description FROM task_history WHERE task_id=?", (task_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else "Unknown"

    def _deliver_artifacts(self, result: dict, task_id: str):
        """Deliver files produced by the worker back to the originating input source."""
        artifact_files = result.get("artifact_files", [])
        if not artifact_files:
            return

        source = self._get_task_source(task_id)
        logger.info(f"[ARTIFACTS] Delivering {len(artifact_files)} file(s) to source='{source}'")

        for af in artifact_files:
            try:
                content = base64.b64decode(af["content_b64"])
                name = af.get("name", "file")
                mime = af.get("mime_type", "application/octet-stream")
                size_bytes = af.get("size_bytes", 0)
                size_kb = size_bytes // 1024

                if source == "telegram":
                    self._deliver_artifact_telegram(content, name, mime, size_kb)
                else:
                    # CLI / TUI / API: save to output dir and print path
                    self._deliver_artifact_local(content, name, task_id, size_kb, source)
            except Exception as e:
                logger.warning(f"[ARTIFACTS] Failed to deliver '{af.get('name')}': {e}")

    def _deliver_artifact_telegram(self, content: bytes, name: str, mime: str, size_kb: int):
        """Send an artifact to Telegram using the appropriate media method for its type.

        Routing:
          image/*  → sendPhoto   (renders inline)
          video/*  → sendVideo   (plays inline)
          audio/*  → sendAudio   (plays inline)
          everything else → sendDocument (generic file)

        Files larger than Telegram's 50 MB limit get a notice instead.
        """
        if not self.notifier:
            return
        MAX_TG_BYTES = 50 * 1024 * 1024
        if len(content) > MAX_TG_BYTES:
            self.notifier.send_message(
                f"⚠️ *File too large for Telegram*\n`{name}` ({size_kb} KB)\n"
                f"The file exceeds Telegram's 50 MB limit. It has been saved on the worker node.\n"
                f"Access it via the server or request a download link."
            )
            return

        caption = f"{name} ({size_kb} KB)"

        if mime.startswith("image/"):
            ok = self.notifier.send_photo(content, caption=caption)
        elif mime.startswith("video/"):
            ok = self.notifier.send_video(content, name, caption=caption)
        elif mime.startswith("audio/"):
            ok = self.notifier.send_audio(content, name, caption=caption)
        else:
            ok = self.notifier.send_document(content, name, caption=caption)

        if ok:
            logger.info(f"[ARTIFACTS] Sent '{name}' ({mime}) to Telegram")
        else:
            self.notifier.send_message(
                f"⚠️ Could not send `{name}` ({mime}) to Telegram.\n"
                f"The file type may not be supported. Try requesting it in a different format."
            )

    def _deliver_artifact_local(self, content: bytes, name: str, task_id: str, size_kb: int, source: str):
        """Save artifact to output/ directory and print the path for CLI/TUI/API sources."""
        out_dir = os.path.join("output", task_id)
        os.makedirs(out_dir, exist_ok=True)
        filepath = os.path.join(out_dir, name)
        with open(filepath, "wb") as f:
            f.write(content)
        abs_path = os.path.abspath(filepath)
        print(f"\n📁 [{source.upper()}] Artifact saved: {abs_path} ({size_kb} KB)")
        logger.info(f"[ARTIFACTS] Saved '{name}' to {abs_path}")

    def _send_text(self, source: str, plain: str, telegram: str = None):
        """Route a text notification to the correct output channel based on originating source.

        Args:
            source:   The source string stored at submission time ('telegram', 'cli', 'tui', 'web', …).
            plain:    Plain-text version of the message (for CLI / TUI / logs).
            telegram: Markdown-formatted version for Telegram.  Falls back to ``plain`` if omitted.
        """
        if source == "telegram":
            if self.notifier:
                self.notifier.send_message(telegram or plain)
        elif source in ("cli", "tui"):
            print(plain)
        elif source == "web":
            # Web interface polls SQLite / Redis — nothing to push synchronously yet.
            logger.info(f"[WEB OUTPUT] {plain[:300]}")
        else:
            # Unknown / future source — degrade gracefully to stdout.
            print(plain)

    def get_recent_tasks(self, limit: int = 20) -> list:
        """Return recent tasks from the local history table, newest first."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute("SELECT task_id, description, submitted_at, status FROM task_history ORDER BY submitted_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return [{"task_id": r[0], "description": r[1], "submitted_at": r[2], "status": r[3]} for r in rows]

    async def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        """Query Temporal for live workflow status and combine with local history."""
        description = self._get_task_description(task_id)
        detail = {"task_id": task_id, "description": description, "status": "UNKNOWN", "result": None}

        if task_id.startswith("QUEUED_OFFLINE"):
            detail["status"] = "QUEUED_OFFLINE"
            return detail

        try:
            temp_cfg = self.config.get("temporal", {})
            temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
            client = await asyncio.wait_for(Client.connect(temporal_host), timeout=10.0)
            handle = client.get_workflow_handle(task_id)
            desc = await handle.describe()

            from temporalio.client import WorkflowExecutionStatus
            status_map = {
                WorkflowExecutionStatus.RUNNING: "RUNNING",
                WorkflowExecutionStatus.COMPLETED: "COMPLETED",
                WorkflowExecutionStatus.FAILED: "FAILED",
                WorkflowExecutionStatus.CANCELED: "CANCELED",
                WorkflowExecutionStatus.TERMINATED: "TERMINATED",
                WorkflowExecutionStatus.TIMED_OUT: "TIMED_OUT",
            }
            detail["status"] = status_map.get(desc.status, str(desc.status))
            detail["start_time"] = str(desc.start_time) if desc.start_time else None
            detail["close_time"] = str(desc.close_time) if desc.close_time else None

            if desc.status == WorkflowExecutionStatus.COMPLETED:
                try:
                    res = await handle.result()
                    detail["result"] = res
                    if isinstance(res, dict) and "status" in res:
                        detail["status"] = res["status"].upper()
                except Exception:
                    pass

            # Sync local status
            self._update_task_status(task_id, detail["status"])
        except Exception as e:
            logger.warning(f"⚠️  Could not query Temporal for task {task_id}: {e}")
            # Fall back to local status
            conn = sqlite3.connect(self.offline_db_path)
            c = conn.cursor()
            c.execute("SELECT status FROM task_history WHERE task_id=?", (task_id,))
            row = c.fetchone()
            conn.close()
            if row:
                detail["status"] = row[0]

        return detail

    async def check_connectivity(self) -> Dict[str, bool]:
        """
        Check reachability of core nodes/services.
        """
        results = {}
        
        # 1. Check Temporal
        temp_cfg = self.config.get("temporal", {})
        host = temp_cfg.get("host", "localhost")
        port = temp_cfg.get("port", 7233)
        results["temporal"] = self._check_tcp(host, port)
        
        # 2. Check Qdrant
        qdrant_cfg = self.config.get("qdrant", {})
        results["qdrant"] = self._check_tcp(qdrant_cfg.get("host", host), qdrant_cfg.get("port", 6333))
        
        # 3. Check Redis
        redis_cfg = self.config.get("redis", {})
        results["redis"] = self._check_tcp(redis_cfg.get("host", host), redis_cfg.get("port", 6379))
        
        return results

    def _check_tcp(self, host: str, port: int, timeout: int = 3) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    async def flush_offline_queue(self, client) -> int:
        """
        Attempt to resubmit any locally queued (offline) tasks to Temporal.
        Returns the number of tasks successfully flushed.
        """
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute("SELECT task_id, description, metadata FROM offline_tasks WHERE status='QUEUED'")
        rows = c.fetchall()
        conn.close()

        flushed = 0
        for task_id, description, meta_str in rows:
            try:
                metadata = json.loads(meta_str) if meta_str else {}
                model_id = metadata.get("llm_model_id", "low")
                provider = metadata.get("model_details", {}).get("provider", "google")
                await client.start_workflow(
                    "AIOrchestrationWorkflow",
                    args=[description, model_id, provider],
                    id=task_id,
                    task_queue="ai-orchestration-queue"
                )
                conn = sqlite3.connect(self.offline_db_path)
                c = conn.cursor()
                c.execute("UPDATE offline_tasks SET status='FLUSHED' WHERE task_id=?", (task_id,))
                conn.commit()
                conn.close()
                logger.info(f"✅ [OFFLINE FLUSH] Task {task_id} submitted to Temporal.")
                if self.notifier:
                    self.notifier.send_message(f"🔄 *Offline Task Flushed*\nID: `{task_id}`\nDescription: {description}")
                flushed += 1
            except Exception as e:
                logger.warning(f"⚠️  Could not flush offline task {task_id}: {e}")

        if flushed:
            logger.info(f"✅ [OFFLINE FLUSH] {flushed}/{len(rows)} queued tasks flushed to Temporal.")
        return flushed

    async def submit_agent_task(self, task_description: str, analysis_result: Dict[str, Any],
                               repo_url: str = "", max_tool_calls: int = 50,
                               max_cost_usd: float = 0.50) -> str:
        """Submit an agent-mode task by wrapping the description in a JSON payload."""
        agent_payload = json.dumps({
            "task_type": "agent",
            "description": task_description,
            "repo_url": repo_url,
            "max_tool_calls": max_tool_calls,
            "max_cost_usd": max_cost_usd,
            "specialization": analysis_result.get("specialization", "general")
        })
        return await self.submit_task(agent_payload, analysis_result)

    async def submit_task(self, task_description: str, analysis_result: Dict[str, Any], source: str = "cli") -> str:
        task_id = str(uuid.uuid4())
        self._record_task(task_id, task_description, source=source)

        # [NEW] Pre-flight Knowledge Base Check with Cache
        logger.info(f"🧠 [CNC NODE] Querying Knowledge Base for relevant past issues...")
        cache_key = task_description.lower().strip()
        
        warnings = []
        if True:
            if cache_key in self.preflight_cache:
                logger.info("⚡ Using cached Knowledge Base lookup.")
                warnings = self.preflight_cache[cache_key]
            else:
                kb = None
                try:
                    from src.shared.memory.knowledge_base import KnowledgeBaseClient
                    kb = KnowledgeBaseClient()
                    warnings = kb.query_similar_issues(task_description, limit=2)
                    self.preflight_cache[cache_key] = warnings
                except Exception as e:
                    logger.warning(f"⚠️  Knowledge Base lookup failed or is unconfigured: {e}")
                finally:
                    if kb:
                        kb.close()

        if warnings:
            logger.warning("⚠️  WARNING: Found similar past issues that you should be aware of:")
            for w in warnings:
                logger.warning(f"  - {w['title']} (Relevance: {w['score']:.2f})")
            
            # Non-interactive mode (e.g. for Telegram bot or CLI with --yolo)
            # We log it and proceed for now, but in a production bot we might want a 'confirm' button in Telegram.
            logger.info("⏳ [HEADLESS] Proceeding despite warnings...")
        else:
            logger.info("✅ No highly relevant past issues found.")
            
        logger.debug("-" * 50)
        
        # [NEW] Save task description to Redis for Observability Web Dashboard
        try:
            import redis
            redis_cfg = self.config.get("redis", {})
            redis_host = redis_cfg.get("host", "localhost")
            redis_port = redis_cfg.get("port", 6379)
            logger.debug(f"Connecting to Redis at {redis_host}:{redis_port}")
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True, socket_connect_timeout=5)
            r.setex(f"obs:task_desc:{task_id}", 604800, task_description)
        except Exception as e:
            logger.warning(f"⚠️  Could not save task description to Redis: {e}")

        
        self._send_text(
            source,
            plain=f"🚀 Task Submitted [{task_id}]\n{task_description[:200]}",
            telegram=f"🚀 *New Task Submitted*\nID: `{task_id}`\nDescription: {task_description[:200]}",
        )

        if self.queue_url == "dummy-temporal-queue":
            logger.info("🚀 [GENESIS CNC] Delegating task to Temporal cluster on Central Node...")
            try:
                temp_cfg = self.config.get("temporal", {})
                host = temp_cfg.get('host', 'localhost')
                port = temp_cfg.get('port', 7233)
                temporal_host = f"{host}:{port}"
                
                logger.debug(f"temp_cfg={temp_cfg}")
                logger.debug(f"Connecting to Temporal at {temporal_host}...")
                client = await asyncio.wait_for(Client.connect(temporal_host), timeout=30.0)
                # Flush any previously offline-queued tasks now that we're connected
                await self.flush_offline_queue(client)

                logger.info(f"Pushing task to Temporal workflow...")

                model_id = analysis_result['llm_model_id']
                provider = analysis_result['model_details']['provider']
                
                await client.start_workflow(
                    "AIOrchestrationWorkflow",
                    args=[task_description, model_id, provider],
                    id=task_id,
                    task_queue="ai-orchestration-queue"
                )
                return task_id
            except (Exception, asyncio.TimeoutError) as e:
                logger.error(f"❌ Error connecting to Temporal: {e}", exc_info=True)
                self._send_text(
                    source,
                    plain=f"⚠️  Temporal connection failed — task queued offline.\nError: {e}",
                    telegram=f"⚠️ *Temporal Connection Failed*\nError: `{e}`\nFalling back to offline mode.",
                )
                logger.info("Falling back to local offline queue...")
                self._save_task_offline(task_id, task_description, analysis_result)
                return f"QUEUED_OFFLINE_{task_id}"
            
        # 1. Register in DynamoDB
        self.table.put_item(Item={
            'task_id': task_id,
            'description': task_description,
            'status': 'PENDING',
            'created_at': int(time.time()),
            'metadata': analysis_result or {}
        })
        
        # 2. Push to SQS
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({
                "task_id": task_id,
                "task_description": task_description,
                "llm_model_id": analysis_result['llm_model_id'],
                "provider": analysis_result['model_details']['provider']
            })
        )
        
        return task_id

    def get_task_status(self, task_id: str) -> str:
        if task_id.startswith("QUEUED_OFFLINE"):
            return "QUEUED_OFFLINE"
            
        if self.queue_url == "dummy-temporal-queue":
            return "RUNNING" 
            
        response = self.table.get_item(Key={'task_id': task_id})
        item = response.get('Item')
        return item.get('status', 'NOT_FOUND') if item else 'NOT_FOUND'

    async def wait_for_completion(self, task_id: str, timeout: int = 600) -> str:
        if task_id.startswith("QUEUED_OFFLINE") or task_id == "CANCELLED":
            return task_id

        if self.queue_url == "dummy-temporal-queue":
            source = self._get_task_source(task_id)
            try:
                temp_cfg = self.config.get("temporal", {})
                temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
                client = await Client.connect(temporal_host)
                handle = client.get_workflow_handle(task_id)

                logger.info(f"⏳ [CENTRAL NODE] Polling for worker progress on task {task_id}...")
                last_progress = None
                notified_running = False
                from temporalio.client import WorkflowExecutionStatus

                while True:
                    desc = await handle.describe()
                    if desc.status != WorkflowExecutionStatus.RUNNING:
                        break

                    # Notify once when worker picks up the task
                    if not notified_running:
                        self._send_text(
                            source,
                            plain=f"⚙️  Task Running [{task_id}] — Worker has picked up the task.",
                            telegram=f"⚙️ *Task Running*\nID: `{task_id}`\nWorker has picked up the task.",
                        )
                        notified_running = True

                    if desc.raw_description.pending_activities:
                        act = desc.raw_description.pending_activities[0]
                        if act.heartbeat_details:
                            from temporalio.converter import default
                            try:
                                payloads = act.heartbeat_details.payloads
                                current_progress = default().payload_converter.from_payloads(payloads)[0]
                                if current_progress != last_progress:
                                    display = current_progress
                                    if isinstance(current_progress, str) and current_progress.startswith("{"):
                                        try:
                                            hb = json.loads(current_progress)
                                            display = f"Step {hb.get('step', '?')}/{hb.get('max_steps', '?')} | ${hb.get('cost_usd', 0):.4f} | {hb.get('phase', '')}"
                                            if hb.get("last_tool"):
                                                display += f" | last: {hb['last_tool']}"
                                        except (json.JSONDecodeError, TypeError):
                                            pass
                                    logger.info(f"📈 Worker Progress: {display}")
                                    if current_progress != "0%":
                                        self._send_text(
                                            source,
                                            plain=f"📈 Progress: {display}",
                                            telegram=f"📈 *Progress*: {display}\nTask: `{task_id}`",
                                        )
                                    last_progress = current_progress
                            except Exception:
                                pass

                    await asyncio.sleep(1.0)

                result = await handle.result()
                final_status = result.get("status", "COMPLETED").upper()
                logger.info(f"✅ [CENTRAL NODE] Worker Execution Finished with status: {final_status}")
                self._update_task_status(task_id, final_status)

                cost = result.get('total_cost_usd', 0.0)
                if result.get('mode') == 'agent':
                    summary = result.get('summary', 'No summary.')
                    tool_calls = result.get('tool_call_count', 0)
                    duration = result.get('duration_seconds', 0)
                    truncated = summary[:2000] + ('...' if len(summary) > 2000 else '')
                    self._send_text(
                        source,
                        plain=(
                            f"✅ Agent Task Succeeded\n"
                            f"ID: {task_id}\n"
                            f"Cost: ${cost:.6f} USD  |  Tool calls: {tool_calls}  |  Duration: {duration:.1f}s\n\n"
                            f"Summary:\n{truncated}"
                        ),
                        telegram=(
                            f"✅ *Agent Task Succeeded*\n"
                            f"ID: `{task_id}`\n"
                            f"💰 *Cost:* ${cost:.6f} USD\n"
                            f"🔧 *Tool Calls:* {tool_calls}\n"
                            f"⏱ *Duration:* {duration:.1f}s\n\n"
                            f"📋 *Summary:*\n{truncated}"
                        ),
                    )
                else:
                    recommendations = result.get('recommendations', '')
                    brief = recommendations[:300] + '...' if len(recommendations) > 300 else recommendations
                    description = self._get_task_description(task_id)
                    self._send_text(
                        source,
                        plain=(
                            f"✅ Task Succeeded\n"
                            f"ID: {task_id}\n"
                            f"Task: {description[:200]}\n"
                            f"Cost: ${cost:.6f} USD\n\n"
                            f"Result:\n{brief}"
                        ),
                        telegram=(
                            f"✅ *Task Succeeded*\n"
                            f"ID: `{task_id}`\n"
                            f"📝 *Task:* {description[:200]}\n"
                            f"💰 *Cost:* ${cost:.6f} USD\n\n"
                            f"💡 *Result:*\n{brief}"
                        ),
                    )

                self._deliver_artifacts(result, task_id)
                return final_status

            except Exception as e:
                logger.error(f"❌ Error waiting for Temporal workflow: {e}", exc_info=True)
                self._update_task_status(task_id, "FAILED")
                self._send_text(
                    source,
                    plain=f"❌ Task Failed [{task_id}]\nError: {e}",
                    telegram=f"❌ *Task Failed*\nID: `{task_id}`\n\n*Error:*\n{e}",
                )
                return "FAILED"
            
        source = self._get_task_source(task_id)
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.table.get_item(Key={'task_id': task_id})
            item = response.get('Item', {})
            status = item.get('status', 'PENDING')

            if status == 'COMPLETED':
                result = item.get('result', 'No result detail provided.')
                logger.info(f"✅ Task {task_id} COMPLETED.")
                self._send_text(
                    source,
                    plain=f"✅ Task Succeeded [{task_id}]\n\nSummary:\n{result}",
                    telegram=f"✅ *Task Succeeded*\nID: `{task_id}`\n\n*Summary:*\n{result}",
                )
                return status
            elif status == 'FAILED':
                reason = item.get('error', 'Unknown error.')
                logger.info(f"❌ Task {task_id} FAILED.")
                self._send_text(
                    source,
                    plain=f"❌ Task Failed [{task_id}]\nReason: {reason}",
                    telegram=f"❌ *Task Failed*\nID: `{task_id}`\n\n*Reason:*\n{reason}",
                )
                return status

            logger.info(f"⌛ Task {task_id} is {status}...")
            await asyncio.sleep(10)

        self._send_text(
            source,
            plain=f"⚠️  Task Timeout [{task_id}] — exceeded {timeout}s.",
            telegram=f"⚠️ *Task Timeout*\nID: `{task_id}`\nTask exceeded {timeout}s.",
        )
        return "TIMEOUT"

