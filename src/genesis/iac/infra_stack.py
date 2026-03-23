import pulumi
import pulumi_aws as aws
import pulumi_docker as docker

# --- 1. Cloud LTM (Production) ---
# Provision a small, persistent Qdrant instance on AWS
def create_cloud_ltm():
    # Security Group for Qdrant (Port 6333)
    ltm_sg = aws.ec2.SecurityGroup('ltm-sg',
        description='Enable Qdrant access',
        ingress=[
            {'protocol': 'tcp', 'from_port': 6333, 'to_port': 6333, 'cidr_blocks': ['0.0.0.0/0']},
            {'protocol': 'tcp', 'from_port': 22, 'to_port': 22, 'cidr_blocks': ['0.0.0.0/0']},
        ])

    # Small EC2 Instance for Qdrant
    qdrant_instance = aws.ec2.Instance('qdrant-ltm',
        instance_type='t4g.small', # ARM-based, cost-efficient
        vpc_security_group_ids=[ltm_sg.id],
        ami='ami-0eb11029c991e528b', # Amazon Linux 2023 ARM64
        tags={'Name': 'Agent-LTM-Store'})
    
    return qdrant_instance

# --- 2. Local Testing Environment (Experimental) ---
# Use Docker on your local network server (192.168.100.249) to mock the infrastructure
def create_local_test_env():
    # Configure the Docker Provider to talk to your remote server
    # Note: Requires SSH or TCP access enabled on the remote docker daemon
    remote_docker = docker.Provider("remote-docker",
        host="ssh://rinehardramos@192.168.100.249")

    # Local Qdrant Container for testing RAG
    qdrant_container = docker.Container("test-qdrant",
        image="qdrant/qdrant:latest",
        ports=[{"internal": 6333, "external": 6333}],
        name="experimental-ltm",
        opts=pulumi.ResourceOptions(provider=remote_docker))

    # Local Temporal Server for testing Workflows
    temporal_container = docker.Container("test-temporal",
        image="temporalio/admin-tools:latest",
        name="experimental-temporal",
        opts=pulumi.ResourceOptions(provider=remote_docker))
    
    return qdrant_container, temporal_container

# Execution logic based on Pulumi Stack (dev/prod)
stack = pulumi.get_stack()
if stack == "prod":
    qdrant = create_cloud_ltm()
    pulumi.export('ltm_endpoint', qdrant.public_ip)
else:
    qdrant_test, temporal_test = create_local_test_env()
    pulumi.export('test_ltm_status', qdrant_test.state)
