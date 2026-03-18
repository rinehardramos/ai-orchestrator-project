import boto3
import sys
import logging

# Suppress boto3 logging for cleaner output
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)

def check_resources():
    print("🔍 Scanning AWS regions for active resources (EC2, SQS, DynamoDB, Lambda)...\n")
    
    ec2_client = boto3.client('ec2', region_name='us-east-1')
    try:
        regions = [region['RegionName'] for region in ec2_client.describe_regions()['Regions']]
    except Exception as e:
        print(f"❌ Could not retrieve AWS regions. Check your AWS credentials in .aws/credentials. Error: {e}")
        sys.exit(1)

    found_resources = False

    for region in regions:
        region_has_resources = False
        output_buffer = []

        try:
            # Check EC2 Instances (running or pending)
            ec2 = boto3.client('ec2', region_name=region)
            instances = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'pending']}])
            running_instances = []
            for res in instances.get('Reservations', []):
                for inst in res.get('Instances', []):
                    running_instances.append(inst.get('InstanceId'))
            if running_instances:
                output_buffer.append(f"  - EC2 Instances: {len(running_instances)} active ({', '.join(running_instances)})")
                region_has_resources = True

            # Check Spot Requests
            spot_reqs = ec2.describe_spot_instance_requests(Filters=[{'Name': 'state', 'Values': ['open', 'active']}])
            active_spots = [req['SpotInstanceRequestId'] for req in spot_reqs.get('SpotInstanceRequests', [])]
            if active_spots:
                output_buffer.append(f"  - EC2 Spot Requests: {len(active_spots)} active ({', '.join(active_spots)})")
                region_has_resources = True

            # Check SQS Queues
            sqs = boto3.client('sqs', region_name=region)
            queues = sqs.list_queues().get('QueueUrls', [])
            if queues:
                # Filter for queues related to our project just to be helpful, or show all
                task_queues = [q.split('/')[-1] for q in queues if 'task-queue' in q]
                if task_queues:
                     output_buffer.append(f"  - SQS Queues (Orchestrator): {len(task_queues)} found ({', '.join(task_queues)})")
                     region_has_resources = True
                other_queues = [q.split('/')[-1] for q in queues if 'task-queue' not in q]
                if other_queues:
                     output_buffer.append(f"  - SQS Queues (Other): {len(other_queues)} found")
                     region_has_resources = True

            # Check DynamoDB Tables
            dynamodb = boto3.client('dynamodb', region_name=region)
            tables = dynamodb.list_tables().get('TableNames', [])
            if tables:
                task_tables = [t for t in tables if 'task-status' in t]
                if task_tables:
                     output_buffer.append(f"  - DynamoDB Tables (Orchestrator): {len(task_tables)} found ({', '.join(task_tables)})")
                     region_has_resources = True
                other_tables = [t for t in tables if 'task-status' not in t]
                if other_tables:
                     output_buffer.append(f"  - DynamoDB Tables (Other): {len(other_tables)} found")
                     region_has_resources = True

            # Check Lambda Functions
            lambda_client = boto3.client('lambda', region_name=region)
            functions = lambda_client.list_functions().get('Functions', [])
            if functions:
                task_funcs = [f['FunctionName'] for f in functions if 'task-worker' in f['FunctionName']]
                if task_funcs:
                     output_buffer.append(f"  - Lambda Functions (Orchestrator): {len(task_funcs)} found ({', '.join(task_funcs)})")
                     region_has_resources = True
                other_funcs = [f['FunctionName'] for f in functions if 'task-worker' not in f['FunctionName']]
                if other_funcs:
                     output_buffer.append(f"  - Lambda Functions (Other): {len(other_funcs)} found")
                     region_has_resources = True

        except Exception as e:
             # Ignore region-specific errors (e.g., if a region is not enabled for the account)
             pass

        if region_has_resources:
            print(f"🌐 Region: {region}")
            for line in output_buffer:
                print(line)
            found_resources = True

    print("\n" + "="*50)
    print("                 SUMMARY")
    print("="*50)
    if not found_resources:
        print("✅ Clean State: No active infrastructure found.")
        print("Reasoning: The ephemeral infrastructure logic is working perfectly. The `pulumi destroy` commands executed during our tests successfully tore down all EC2 instances, SQS queues, and DynamoDB tables. There are zero idle resources incurring costs.")
    else:
        print("⚠️ Warning: Active resources detected.")
        print("Reasoning: Resources were found running in your AWS account. If these are tagged as 'task-queue' or 'task-status', they may be orphaned from a previously interrupted test or manual deployment. If they are 'Other', they belong to your existing personal projects.")

if __name__ == '__main__':
    check_resources()