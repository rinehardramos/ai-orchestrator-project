import os
from pulumi import automation as auto
from typing import Dict, Any

def create_pulumi_program(infra_id: str, task_env: dict):
    def pulumi_program():
        import pulumi
        import pulumi_aws as aws

        # 1. Shared Infrastructure (Queue & Status Table)
        task_queue = aws.sqs.Queue("task-queue", 
            visibility_timeout_seconds=300, # 5 min default
            message_retention_seconds=86400 # 1 day
        )
        
        status_table = aws.dynamodb.Table("task-status",
            attributes=[aws.dynamodb.TableAttributeArgs(name="task_id", type="S")],
            hash_key="task_id",
            billing_mode="PAY_PER_REQUEST"
        )

        pulumi.export("queue_url", task_queue.url)
        pulumi.export("table_name", status_table.name)

        # 2. Worker-specific provisioning
        if infra_id == "aws_ec2_spot_t4g":
            ami = aws.ec2.get_ami(
                most_recent=True,
                owners=["amazon"],
                filters=[{"name": "name", "values": ["al2023-ami-2023.*-arm64"]}]
            )
            
            # Updated UserData to include SQS/DynamoDB polling logic (consistent with worker_runner.py)
            user_data = f"""#!/bin/bash
            dnf update -y
            dnf install -y python3-pip unzip git
            # Install AWS CLI
            curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
            unzip awscliv2.zip && sudo ./aws/install
            # Setup AI environment
            pip3 install google-genai boto3
            
            # Use the shared worker runner script
            cat <<EOF > /home/ec2-user/worker_runner.py
            {open('src/orchestrator/worker_runner.py').read()}
            EOF
            
            export TASK_QUEUE_URL='{task_queue.url}'
            export STATUS_TABLE_NAME='{status_table.name}'
            export AWS_REGION='us-east-1'
            python3 /home/ec2-user/worker_runner.py &
            """

            spot_req = aws.ec2.SpotInstanceRequest("task-worker-spot",
                ami=ami.id,
                instance_type="t4g.small", 
                spot_price="0.005",
                wait_for_fulfillment=True,
                user_data=user_data,
                tags={"Name": "ephemeral-ai-agent-worker"}
            )
            pulumi.export("instance_id", spot_req.id)

        elif infra_id == "local_server_docker":
            import pulumi_docker as docker
            
            # The user must have DOCKER_HOST=ssh://user@hostname set in their env
            # or we could pass it via Pulumi config.
            
            image = docker.Image("worker-image",
                build=docker.DockerBuildArgs(
                    context=".",
                    dockerfile="Dockerfile",
                    platform="linux/arm64" # Adjust if your local server is x86
                ),
                image_name="ai-orchestrator-worker:latest",
                skip_push=True # Local network deployment doesn't need a registry push
            )

            container = docker.Container("worker-container",
                image=image.base_image_name,
                envs=[
                    f"TASK_QUEUE_URL={task_queue.url}",
                    f"STATUS_TABLE_NAME={status_table.name}",
                    f"AWS_REGION=us-east-1",
                    f"GOOGLE_API_KEY={os.getenv('GOOGLE_API_KEY')}",
                    f"AWS_ACCESS_KEY_ID={os.getenv('AWS_ACCESS_KEY_ID')}",
                    f"AWS_SECRET_ACCESS_KEY={os.getenv('AWS_SECRET_ACCESS_KEY')}"
                ],
                restart="always"
            )
            pulumi.export("container_id", container.id)
            
        elif "lambda" in infra_id:
            role = aws.iam.Role("lambdaRole", assume_role_policy="""{
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": "sts:AssumeRole",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Effect": "Allow"
                }]
            }""")
            
            # Give Lambda permissions to SQS and DynamoDB
            aws.iam.RolePolicy("lambdaPolicy", role=role.id, policy=pulumi.Output.all(task_queue.arn, status_table.arn).apply(lambda args: f"""{{
                "Version": "2012-10-17",
                "Statement": [
                    {{ "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], "Resource": "{args[0]}", "Effect": "Allow" }},
                    {{ "Action": ["dynamodb:UpdateItem", "dynamodb:PutItem"], "Resource": "{args[1]}", "Effect": "Allow" }},
                    {{ "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], "Resource": "arn:aws:logs:*:*:*", "Effect": "Allow" }}
                ]
            }}"""))

            handler_code = f"""
            import boto3
            import os
            def handler(event, context):
                db = boto3.resource('dynamodb')
                table = db.Table('{status_table.name}')
                # Extract task from SQS trigger
                for record in event.get('Records', []):
                    task_id = record['body']
                    table.update_item(Key={{'task_id': task_id}}, UpdateExpression='SET #s = :s', ExpressionAttributeNames={{'#s': 'status'}}, ExpressionAttributeValues={{':s': 'RUNNING'}})
                    # ... Task Logic ...
                    table.update_item(Key={{'task_id': task_id}}, UpdateExpression='SET #s = :s', ExpressionAttributeNames={{'#s': 'status'}}, ExpressionAttributeValues={{':s': 'COMPLETED'}})
                return {{"status": "ok"}}
            """

            func = aws.lambda_.Function("task-worker-lambda",
                role=role.arn,
                runtime="python3.11",
                handler="index.handler",
                code=pulumi.AssetArchive({"index.py": pulumi.StringAsset(handler_code)})
            )
            # Trigger Lambda on SQS messages
            aws.lambda_.EventSourceMapping("lambda-sqs-trigger",
                event_source_arn=task_queue.arn,
                function_name=func.name
            )
            pulumi.export("lambda_arn", func.arn)
        else:
            pulumi.log.warn(f"Unsupported infra_id for IaC: {infra_id}")

    return pulumi_program

async def provision_worker(stack_name: str, project_name: str, infra_id: str, task_env: Dict[str, Any]):
    """
    Provisions the infrastructure using Pulumi Automation API.
    """
    program = create_pulumi_program(infra_id, task_env)
    
    stack = await auto.create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=program
    )
    
    print(f"[{stack_name}] Successfully initialized stack.")
    
    # Set AWS region if using AWS
    if "aws" in infra_id:
        await stack.set_config("aws:region", auto.ConfigValue(value="us-east-1"))
        
    print(f"[{stack_name}] Starting update...")
    up_res = await stack.up(on_output=print)
    print(f"[{stack_name}] Update complete! Outputs: {up_res.outputs}")
    
    return up_res.outputs

async def destroy_worker(stack_name: str, project_name: str, infra_id: str):
    """
    Destroys the ephemeral infrastructure.
    """
    # Program is required even for destroy to know what providers to load sometimes,
    # but the state determines what is actually destroyed.
    program = create_pulumi_program(infra_id, {})
    stack = await auto.select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=program
    )
    
    print(f"[{stack_name}] Starting destroy...")
    destroy_res = await stack.destroy(on_output=print)
    print(f"[{stack_name}] Destroy complete!")
    return destroy_res
