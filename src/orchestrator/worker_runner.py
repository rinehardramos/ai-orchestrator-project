import boto3
import os
import time
import subprocess
import json

def run_worker():
    # Use environment variables for configuration
    region = os.getenv('AWS_REGION', 'us-east-1')
    queue_url = os.getenv('TASK_QUEUE_URL')
    table_name = os.getenv('STATUS_TABLE_NAME')
    
    if not queue_url or not table_name:
        print("Missing required environment variables: TASK_QUEUE_URL or STATUS_TABLE_NAME")
        return

    sqs = boto3.client('sqs', region_name=region)
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    print(f"🚀 Worker starting. Polling queue: {queue_url}")

    while True:
        try:
            # Poll SQS for a task message
            msgs = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )
            
            if 'Messages' in msgs:
                msg = msgs['Messages'][0]
                task_id = msg['Body']
                receipt_handle = msg['ReceiptHandle']
                
                print(f"📦 Received Task: {task_id}")
                
                # 1. Update status to RUNNING in DynamoDB
                table.update_item(
                    Key={'task_id': task_id},
                    UpdateExpression='SET #s = :s',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':s': 'RUNNING'}
                )
                
                # 2. Execute Task (Dummy execution for now)
                # In a real scenario, this might trigger another agent or a script.
                time.sleep(5) 
                
                # 3. Update status to COMPLETED in DynamoDB
                table.update_item(
                    Key={'task_id': task_id},
                    UpdateExpression='SET #s = :s',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':s': 'COMPLETED'}
                )
                
                # 4. Delete the message from SQS
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle
                )
                print(f"✅ Task {task_id} Completed.")
                
        except Exception as e:
            print(f"❌ Error in worker loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
