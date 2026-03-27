"""
Temporal workflow definitions for bounty execution.
"""

from datetime import timedelta
from typing import Optional
import logging

from temporalio import workflow, activity

logger = logging.getLogger(__name__)


@workflow.defn
class BountyWorkflow:
    """Workflow for executing a bounty task."""
    
    @workflow.run
    async def run(self, bounty_data: dict) -> dict:
        """Execute the bounty workflow."""
        bounty_id = bounty_data.get("bounty_id")
        description = bounty_data.get("description")
        agent_nickname = bounty_data.get("agent_nickname")
        model_id = bounty_data.get("model_id")
        duration_minutes = bounty_data.get("duration_minutes", 60)
        
        workflow.logger.info(f"Starting bounty {bounty_id} with agent {agent_nickname}")
        
        try:
            result = await workflow.execute_activity(
                execute_bounty_task,
                {
                    "bounty_id": bounty_id,
                    "description": description,
                    "model_id": model_id,
                },
                start_to_close_timeout=timedelta(minutes=duration_minutes + 10),
                heartbeat_timeout=timedelta(minutes=5),
            )
            
            workflow.logger.info(f"Bounty {bounty_id} completed successfully")
            return {
                "status": "completed",
                "result": result.get("summary", ""),
                "artifacts": result.get("artifacts", [])
            }
            
        except Exception as e:
            workflow.logger.error(f"Bounty {bounty_id} failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }


@activity.defn
async def execute_bounty_task(input_data: dict) -> dict:
    """Execute a bounty task using the core orchestrator API."""
    import httpx
    import os
    
    bounty_id = input_data.get("bounty_id")
    description = input_data.get("description")
    model_id = input_data.get("model_id")
    
    core_api_url = os.environ.get("CORE_API_URL", "http://localhost:8000/api/internal")
    core_api_key = os.environ.get("CORE_API_KEY", "")
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{core_api_url}/execute-agent",
            headers={"X-API-Key": core_api_key},
            json={
                "task": description,
                "model_id": model_id,
                "context": {"bounty_id": bounty_id}
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Core API error: {response.text}")
        
        return response.json()
