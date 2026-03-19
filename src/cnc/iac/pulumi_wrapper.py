import os
import yaml
from pulumi import automation as auto
from typing import Dict, Any

# Use the centralized config loader
from src.config import load_settings

def create_pulumi_program(infra_id: str, task_env: dict, env_name: str = None):
    def pulumi_program():
        import pulumi
        settings = load_settings(env_name)
        
        # Initialize Pulumi Config for secrets management
        config = pulumi.Config()
        
        # Securely retrieve API keys (Priority: Pulumi Config Secret > Env Var)
        # If found in Env, we mark it as a secret to ensure it's masked in logs
        google_api_key = config.get_secret("google_api_key") or pulumi.Output.secret(os.environ.get("GOOGLE_API_KEY", ""))

        if "aws" in infra_id:
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
            
            # Read files directly into UserData strings
            docker_compose = open('central_node/docker-compose.yml').read()
            worker_py = open('central_node/worker.py').read()
            dockerfile = open('central_node/Dockerfile.worker').read()
            hybrid_store = open('src/memory/hybrid_store.py').read()
            
            def create_user_data(args):
                q_url, table, api_key = args
                return f"""#!/bin/bash
dnf update -y
dnf install -y docker git
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

curl -SL https://github.com/docker/compose/releases/download/v2.24.1/docker-compose-linux-aarch64 -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

mkdir -p /home/ec2-user/project/central_node
mkdir -p /home/ec2-user/project/src/memory

cat <<'EOF' > /home/ec2-user/project/central_node/docker-compose.yml
{docker_compose}
EOF

cat <<'EOF' > /home/ec2-user/project/central_node/worker.py
{worker_py}
EOF

cat <<'EOF' > /home/ec2-user/project/central_node/Dockerfile.worker
{dockerfile}
EOF

cat <<'EOF' > /home/ec2-user/project/src/memory/hybrid_store.py
{hybrid_store}
EOF
touch /home/ec2-user/project/src/__init__.py
touch /home/ec2-user/project/src/memory/__init__.py

cd /home/ec2-user/project
export TASK_QUEUE_URL='{q_url}'
export STATUS_TABLE_NAME='{table}'
export AWS_REGION='us-east-1'
export GOOGLE_API_KEY='{api_key}'

/usr/local/bin/docker-compose -f central_node/docker-compose.yml up --build -d
"""

            user_data = pulumi.Output.all(task_queue.url, status_table.name, google_api_key).apply(create_user_data)

            spot_req = aws.ec2.SpotInstanceRequest("task-worker-spot",
                ami=ami.id,
                instance_type="t4g.small", 
                spot_price="0.01",
                wait_for_fulfillment=True,
                user_data=user_data,
                tags={"Name": "ephemeral-ai-agent-worker"}
            )
            pulumi.export("instance_id", spot_req.id)

        elif infra_id == "local_server_docker":
            import pulumi_command as command
            
            worker_cfg = settings.get("remote_worker", {})
            remote_host = worker_cfg.get("host", "192.168.100.249")
            remote_port = worker_cfg.get("port", 22)
            remote_user = worker_cfg.get("user", "rinehardramos")
            ssh_key_path = worker_cfg.get("ssh_key_path", "/home/pi/.ssh/id_ed25519")
            project_dir = worker_cfg.get("project_dir", "ai-orchestration-worker")
            
            with open(ssh_key_path, "r") as f:
                private_key = f.read()

            connection = command.remote.ConnectionArgs(
                host=remote_host,
                port=remote_port,
                user=remote_user,
                private_key=private_key,
            )

            # 1. Ensure the project directory exists
            mkdir_cmd = command.remote.Command("mkdir-project-dir",
                create=f"mkdir -p {project_dir}",
                connection=connection
            )

            # 2. Copy necessary files to the remote host
            # We use a trigger to force re-sync when files or environment change
            sync_files = command.local.Command("sync-files-to-worker",
                create=f"scp -P {remote_port} -r central_node src requirements.txt .dockerignore {remote_user}@{remote_host}:{project_dir}/",
                triggers=[str(os.path.getmtime("central_node/docker-compose.worker.yml")), env_name, str(remote_port)],
                opts=pulumi.ResourceOptions(depends_on=[mkdir_cmd])
            )

            # 3. Run docker-compose on the remote host
            # Prepare environment variables for the worker
            temporal_host = f"{settings.get('temporal', {}).get('host', 'localhost')}:{settings.get('temporal', {}).get('port', 7233)}"
            qdrant_url = f"http://{settings.get('qdrant', {}).get('host', 'localhost')}:{settings.get('qdrant', {}).get('port', 6333)}"
            redis_url = f"redis://{settings.get('redis', {}).get('host', 'localhost')}:{settings.get('redis', {}).get('port', 6379)}"
            
            def build_deploy_cmd(api_key):
                return f"bash -l -c 'cd {project_dir} && GOOGLE_API_KEY=\"{api_key}\" TEMPORAL_HOST_URL=\"{temporal_host}\" QDRANT_URL=\"{qdrant_url}\" REDIS_URL=\"{redis_url}\" docker compose -f central_node/docker-compose.worker.yml up --build -d'"

            deploy_cmd = command.remote.Command("deploy-docker-stack",
                create=google_api_key.apply(build_deploy_cmd),
                connection=connection,
                opts=pulumi.ResourceOptions(depends_on=[sync_files])
            )


            pulumi.export("queue_url", pulumi.Output.from_input("dummy-temporal-queue"))
            pulumi.export("table_name", pulumi.Output.from_input("dummy-qdrant-db"))
            pulumi.export("container_id", deploy_cmd.id)

        elif infra_id == "existing_server":
            # We skip provisioning completely and assume the user's infrastructure is already running our worker/services.
            pulumi.export("queue_url", pulumi.Output.from_input("dummy-temporal-queue"))
            pulumi.export("table_name", pulumi.Output.from_input("dummy-qdrant-db"))
            pulumi.export("container_id", pulumi.Output.from_input("existing-server-id"))
            
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
    env_name = os.environ.get("SELECTED_ENV")
    program = create_pulumi_program(infra_id, task_env, env_name)
    
    stack = auto.create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=program
    )
    
    print(f"[{stack_name}] Successfully initialized stack.")
    
    # Set AWS region if using AWS
    if "aws" in infra_id:
        stack.set_config("aws:region", auto.ConfigValue(value="us-east-1"))
        
    print(f"[{stack_name}] Starting update...")
    up_res = stack.up(on_output=print)
    print(f"[{stack_name}] Update complete! Outputs: {up_res.outputs}")
    
    return up_res.outputs

async def destroy_worker(stack_name: str, project_name: str, infra_id: str):
    """
    Destroys the ephemeral infrastructure.
    """
    env_name = os.environ.get("SELECTED_ENV")
    program = create_pulumi_program(infra_id, {}, env_name)
    stack = auto.select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=program
    )
    
    print(f"[{stack_name}] Starting destroy...")
    destroy_res = stack.destroy(on_output=print)
    print(f"[{stack_name}] Destroy complete!")
    return destroy_res
