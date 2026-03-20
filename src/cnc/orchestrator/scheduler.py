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
    from src.cnc.orchestrator.notifier import TelegramNotifier
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

    def _record_task(self, task_id: str, description: str):
        """Record a submitted task in the local history table."""
        conn = sqlite3.connect(self.offline_db_path)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO task_history (task_id, description, submitted_at, status) VALUES (?, ?, ?, ?)",
            (task_id, description, time.time(), "SUBMITTED")
        )
        conn.commit()
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
                    detail["result"] = await handle.result()
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
        })
        return await self.submit_task(agent_payload, analysis_result)

    async def submit_task(self, task_description: str, analysis_result: Dict[str, Any]) -> str:
        task_id = str(uuid.uuid4())
        self._record_task(task_id, task_description)

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
            
        logger.info("-" * 50)
        
        # [NEW] Save task description to Redis for Observability Web Dashboard
        try:
            import redis
            redis_cfg = self.config.get("redis", {})
            redis_host = redis_cfg.get("host", "localhost")
            redis_port = redis_cfg.get("port", 6379)
            logger.info(f"DEBUG: Connecting to Redis at {redis_host}:{redis_port}")
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True, socket_connect_timeout=5)
            r.setex(f"obs:task_desc:{task_id}", 604800, task_description)
        except Exception as e:
            logger.warning(f"⚠️  Could not save task description to Redis: {e}")

        
        if self.notifier:
            self.notifier.send_message(f"🚀 *New Task Submitted*\nID: `{task_id}`\nDescription: {task_description}")

        if self.queue_url == "dummy-temporal-queue":
            logger.info("🚀 [GENESIS CNC] Delegating task to Temporal cluster on Central Node...")
            try:
                temp_cfg = self.config.get("temporal", {})
                host = temp_cfg.get('host', 'localhost')
                port = temp_cfg.get('port', 7233)
                temporal_host = f"{host}:{port}"
                
                logger.info(f"DEBUG: temp_cfg={temp_cfg}")
                logger.info(f"DEBUG: Connecting to Temporal at {temporal_host}...")
                client = await asyncio.wait_for(Client.connect(temporal_host), timeout=30.0)
                # Flush any previously offline-queued tasks now that we're connected
                await self.flush_offline_queue(client)

                logger.info(f"📥 Pushing task '{task_description}' to Temporal workflow...")

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
                if self.notifier:
                    self.notifier.send_message(f"⚠️ *Temporal Connection Failed*\nError: `{e}`\nFalling back to offline mode.")
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
                    if not notified_running and self.notifier:
                        self.notifier.send_message(f"⚙️ *Task Running*\nID: `{task_id}`\nWorker has picked up the task.")
                        notified_running = True

                    if desc.raw_description.pending_activities:
                        act = desc.raw_description.pending_activities[0]
                        if act.heartbeat_details:
                            from temporalio.converter import default
                            try:
                                payloads = act.heartbeat_details.payloads
                                current_progress = default().payload_converter.from_payloads(payloads)[0]
                                if current_progress != last_progress:
                                    # Handle structured agent heartbeats
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
                                    if self.notifier and current_progress != "0%":
                                        self.notifier.send_message(f"📈 *Progress*: {display}\nTask: `{task_id}`")
                                    last_progress = current_progress
                            except Exception:
                                pass

                    await asyncio.sleep(1.0)
                    
                result = await handle.result()
                logger.info(f"✅ [CENTRAL NODE] Worker Execution Complete.")
                self._update_task_status(task_id, "COMPLETED")

                if self.notifier:
                    cost = result.get('total_cost_usd', 0.0)
                    if result.get('mode') == 'agent':
                        summary = result.get('summary', 'No summary.')
                        tool_calls = result.get('tool_call_count', 0)
                        duration = result.get('duration_seconds', 0)
                        msg = (
                            f"✅ *Agent Task Succeeded*\n"
                            f"ID: `{task_id}`\n"
                            f"💰 *Cost:* ${cost:.6f} USD\n"
                            f"🔧 *Tool Calls:* {tool_calls}\n"
                            f"⏱ *Duration:* {duration:.1f}s\n\n"
                            f"📋 *Summary:*\n{summary[:2000]}{'...' if len(summary) > 2000 else ''}"
                        )
                    else:
                        recommendations = result.get('recommendations', '')
                        # Keep Telegram notification concise — full details available via status command
                        brief = recommendations[:300] + '...' if len(recommendations) > 300 else recommendations
                        description = self._get_task_description(task_id)
                        msg = (
                            f"✅ *Task Succeeded*\n"
                            f"ID: `{task_id}`\n"
                            f"📝 *Task:* {description[:200]}\n"
                            f"💰 *Cost:* ${cost:.6f} USD\n\n"
                            f"💡 *Result:*\n{brief}"
                        )
                    self.notifier.send_message(msg)
                    
                return "COMPLETED"
            except Exception as e:
                logger.error(f"❌ Error waiting for Temporal workflow: {e}", exc_info=True)
                self._update_task_status(task_id, "FAILED")
                if self.notifier:
                    msg = f"❌ *Task Failed*\nID: `{task_id}`\n\n*Error:*\n{e}"
                    self.notifier.send_message(msg)
                return "FAILED"
            
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.table.get_item(Key={'task_id': task_id})
            item = response.get('Item', {})
            status = item.get('status', 'PENDING')
            
            if status == 'COMPLETED':
                result = item.get('result', 'No result detail provided.')
                logger.info(f"✅ Task {task_id} COMPLETED.")
                if self.notifier:
                    msg = f"✅ *Task Succeeded*\nID: `{task_id}`\n\n*Summary:*\n{result}"
                    self.notifier.send_message(msg)
                return status
            elif status == 'FAILED':
                reason = item.get('error', 'Unknown error.')
                logger.info(f"❌ Task {task_id} FAILED.")
                if self.notifier:
                    msg = f"❌ *Task Failed*\nID: `{task_id}`\n\n*Reason:*\n{reason}"
                    self.notifier.send_message(msg)
                return status
                
            logger.info(f"⌛ Task {task_id} is {status}...")
            await asyncio.sleep(10)
        
        if self.notifier:
            self.notifier.send_message(f"⚠️ *Task Timeout*\nID: `{task_id}`\nTask exceeded {timeout}s.")
        return "TIMEOUT"

