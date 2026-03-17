import boto3
import uuid
import time
import asyncio
import os
import yaml
import socket
from typing import Dict, Any
from temporalio.client import Client

class TaskScheduler:
    def __init__(self, queue_url: str, table_name: str, region: str = "us-east-1"):
        self.queue_url = queue_url
        self.config = self._load_settings()
        
        if self.queue_url != "dummy-temporal-queue":
            self.sqs = boto3.client('sqs', region_name=region)
            self.dynamodb = boto3.resource('dynamodb', region_name=region)
            self.table = self.dynamodb.Table(table_name)
        else:
            self.sqs = None
            self.dynamodb = None
            self.table = None

    def _load_settings(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        settings_path = os.path.join(project_root, "config/settings.yaml")
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                return yaml.safe_load(f)
        return {}

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

    async def submit_task(self, task_description: str, metadata: Dict[str, Any] = None) -> str:
        task_id = str(uuid.uuid4())
        
        if self.queue_url == "dummy-temporal-queue":
            print("🚀 [GENESIS CNC] Delegating task to Temporal cluster on Central Node...")
            try:
                temp_cfg = self.config.get("temporal", {})
                temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
                
                print(f"Connecting to Temporal at {temporal_host}...")
                client = await Client.connect(temporal_host)
                print(f"📥 Pushing task '{task_description}' to Temporal workflow...")
                
                await client.start_workflow(
                    "AIOrchestrationWorkflow",
                    task_description,
                    id=task_id,
                    task_queue="ai-orchestration-queue"
                )
                return task_id
            except Exception as e:
                print(f"❌ Error connecting to Temporal: {e}")
                return task_id
            
        # 1. Register in DynamoDB
        self.table.put_item(Item={
            'task_id': task_id,
            'description': task_description,
            'status': 'PENDING',
            'created_at': int(time.time()),
            'metadata': metadata or {}
        })
        
        # 2. Push to SQS
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=task_id
        )
        
        return task_id

    def get_task_status(self, task_id: str) -> str:
        if self.queue_url == "dummy-temporal-queue":
            return "RUNNING" 
        response = self.table.get_item(Key={'task_id': task_id})
        item = response.get('Item')
        return item.get('status', 'NOT_FOUND') if item else 'NOT_FOUND'

    async def wait_for_completion(self, task_id: str, timeout: int = 600) -> str:
        if self.queue_url == "dummy-temporal-queue":
            try:
                temp_cfg = self.config.get("temporal", {})
                temporal_host = f"{temp_cfg.get('host', 'localhost')}:{temp_cfg.get('port', 7233)}"
                client = await Client.connect(temporal_host)
                handle = client.get_workflow_handle(task_id)
                result = await handle.result()
                print(f"\n✅ [CENTRAL NODE] Worker Execution Complete.")
                print(f"Result: {result}")
                return "COMPLETED"
            except Exception as e:
                print(f"❌ Error waiting for Temporal workflow: {e}")
                return "FAILED"
            
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_task_status(task_id)
            if status in ['COMPLETED', 'FAILED']:
                return status
            print(f"⌛ Task {task_id} is {status}...")
            await asyncio.sleep(10)
        return "TIMEOUT"
