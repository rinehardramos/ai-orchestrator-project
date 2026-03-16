import boto3
import uuid
import time
from typing import Dict, Any

class TaskScheduler:
    def __init__(self, queue_url: str, table_name: str, region: str = "us-east-1"):
        self.sqs = boto3.client('sqs', region_name=region)
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.table = self.dynamodb.Table(table_name)
        self.queue_url = queue_url

    def submit_task(self, task_description: str, metadata: Dict[str, Any] = None) -> str:
        task_id = str(uuid.uuid4())
        
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
        response = self.table.get_item(Key={'task_id': task_id})
        item = response.get('Item')
        return item.get('status', 'NOT_FOUND') if item else 'NOT_FOUND'

    def wait_for_completion(self, task_id: str, timeout: int = 600) -> str:
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_task_status(task_id)
            if status in ['COMPLETED', 'FAILED']:
                return status
            print(f"⌛ Task {task_id} is {status}...")
            time.sleep(10)
        return "TIMEOUT"
