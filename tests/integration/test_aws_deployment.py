import asyncio
import os
import sys

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.iac.pulumi_wrapper import provision_worker, destroy_worker

async def test_aws_deployment():
    stack_name = "test-aws-worker"
    project_name = "ai-orchestration"
    infra_id = "aws_ec2_spot_t4g" # Choose an AWS infrastructure profile
    
    print(f"🚀 [TEST] Provisioning {infra_id} on AWS...")
    try:
        # Provision the infrastructure
        outputs = await provision_worker(stack_name, project_name, infra_id, {})
        print(f"✅ [TEST] Provisioning successful! Outputs: {outputs}")
        
    except Exception as e:
        print(f"❌ [TEST] Provisioning failed: {e}")
        
    finally:
        print(f"\n🧹 [TEST] Tearing down infrastructure...")
        try:
            # Destroy the infrastructure
            destroy_res = await destroy_worker(stack_name, project_name, infra_id)
            print(f"✅ [TEST] Teardown complete!")
        except Exception as e:
            print(f"❌ [TEST] Teardown failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_aws_deployment())
