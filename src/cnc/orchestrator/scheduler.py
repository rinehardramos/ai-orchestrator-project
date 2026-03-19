import boto3
import uuid
import time
import asyncio
import os
import socket
import sqlite3
import json
from typing import Dict, Any
from temporalio.client import Client

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
        print(f"📴 [OFFLINE] Task {task_id} queued locally. It will be flushed when network is restored.")
        if self.notifier:
            self.notifier.send_message(f"📴 *Offline Mode*: Task {task_id} queued locally.")

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

    async def submit_task(self, task_description: str, analysis_result: Dict[str, Any]) -> str:
        task_id = str(uuid.uuid4())
        
        # [NEW] Pre-flight Knowledge Base Check with Cache
        print(f"\n🧠 [CNC NODE] Querying Knowledge Base for relevant past issues...")
        cache_key = task_description.lower().strip()
        
        warnings = []
        if False: # Temporarily disabled KB lookup due to genai library conflicts
            if cache_key in self.preflight_cache:
                print("⚡ Using cached Knowledge Base lookup.")
                warnings = self.preflight_cache[cache_key]
            else:
                kb = None
                try:
                    from src.shared.memory.knowledge_base import KnowledgeBaseClient
                    kb = KnowledgeBaseClient()
                    warnings = kb.query_similar_issues(task_description, limit=2)
                    self.preflight_cache[cache_key] = warnings
                except Exception as e:
                    print(f"⚠️  Knowledge Base lookup failed or is unconfigured: {e}")
                finally:
                    if kb:
                        kb.close()

        if warnings:
            print("⚠️  WARNING: Found similar past issues that you should be aware of:")
            for w in warnings:
                print(f"  - {w['title']} (Relevance: {w['score']:.2f})")
            
            # Non-interactive mode (e.g. for Telegram bot or CLI with --yolo)
            # We log it and proceed for now, but in a production bot we might want a 'confirm' button in Telegram.
            print("⏳ [HEADLESS] Proceeding despite warnings...")
        else:
            print("✅ No highly relevant past issues found.")
            
        print("-" * 50)
        
        # [NEW] Save task description to Redis for Observability Web Dashboard
        try:
            import redis
            redis_cfg = self.config.get("redis", {})
            redis_host = redis_cfg.get("host", "localhost")
            redis_port = redis_cfg.get("port", 6379)
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
            r.setex(f"obs:task_desc:{task_id}", 604800, task_description)
        except Exception as e:
            print(f"⚠️  Could not save task description to Redis: {e}")

        
        if self.notifier:
            self.notifier.send_message(f"🚀 *New Task Submitted*\nID: `{task_id}`\nDescription: {task_description}")

        if self.queue_url == "dummy-temporal-queue":
            print("🚀 [GENESIS CNC] Delegating task to Temporal cluster on Central Node...")
            try:
                temp_cfg = self.config.get("temporal", {})
                temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
                
                print(f"Connecting to Temporal at {temporal_host}...")
                client = await asyncio.wait_for(Client.connect(temporal_host), timeout=5.0)
                print(f"📥 Pushing task '{task_description}' to Temporal workflow...")

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
                print(f"❌ Error connecting to Temporal: {e}")
                print("Falling back to local offline queue...")
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
                
                print(f"\n⏳ [CENTRAL NODE] Polling for worker progress on task {task_id}...")
                last_progress = None
                from temporalio.client import WorkflowExecutionStatus
                
                while True:
                    desc = await handle.describe()
                    if desc.status != WorkflowExecutionStatus.RUNNING:
                        break
                        
                    if desc.raw_description.pending_activities:
                        act = desc.raw_description.pending_activities[0]
                        if act.heartbeat_details:
                            from temporalio.converter import default
                            try:
                                payloads = act.heartbeat_details.payloads
                                current_progress = default().payload_converter.from_payloads(payloads)[0]
                                if current_progress != last_progress:
                                    print(f"📈 Worker Progress: {current_progress}")
                                    last_progress = current_progress
                            except Exception:
                                pass
                                
                    await asyncio.sleep(1.0)
                    
                result = await handle.result()
                print(f"\n✅ [CENTRAL NODE] Worker Execution Complete.")
                print(f"Result: {result}")
                
                if self.notifier:
                    msg = f"✅ *Task Succeeded*\nID: `{task_id}`\n\n*Summary:*\n{result}"
                    self.notifier.send_message(msg)
                    
                return "COMPLETED"
            except Exception as e:
                print(f"❌ Error waiting for Temporal workflow: {e}")
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
                print(f"✅ Task {task_id} COMPLETED.")
                if self.notifier:
                    msg = f"✅ *Task Succeeded*\nID: `{task_id}`\n\n*Summary:*\n{result}"
                    self.notifier.send_message(msg)
                return status
            elif status == 'FAILED':
                reason = item.get('error', 'Unknown error.')
                print(f"❌ Task {task_id} FAILED.")
                if self.notifier:
                    msg = f"❌ *Task Failed*\nID: `{task_id}`\n\n*Reason:*\n{reason}"
                    self.notifier.send_message(msg)
                return status
                
            print(f"⌛ Task {task_id} is {status}...")
            await asyncio.sleep(10)
        
        if self.notifier:
            self.notifier.send_message(f"⚠️ *Task Timeout*\nID: `{task_id}`\nTask exceeded {timeout}s.")
        return "TIMEOUT"
