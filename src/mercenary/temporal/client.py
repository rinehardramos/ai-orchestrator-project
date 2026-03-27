"""
Temporal client for mercenary service.
"""

import logging
from typing import Optional

from temporalio.client import Client

from src.mercenary.config import config

logger = logging.getLogger(__name__)


class MercenaryTemporalClient:
    """
    Isolated Temporal client using separate namespace.
    Workers only process mercenary-bounties queue.
    """
    
    _client: Optional[Client] = None
    
    async def connect(self) -> Client:
        if self._client is None:
            self._client = await Client.connect(
                config.TEMPORAL_HOST,
                namespace=config.TEMPORAL_NAMESPACE
            )
            logger.info(f"Connected to Temporal: {config.TEMPORAL_HOST}, namespace: {config.TEMPORAL_NAMESPACE}")
        return self._client
    
    async def submit_bounty(self, bounty_id: str, bounty_data: dict) -> str:
        """Submit bounty to isolated task queue."""
        from src.mercenary.temporal.workflows import BountyWorkflow
        
        client = await self.connect()
        
        handle = await client.start_workflow(
            BountyWorkflow.run,
            bounty_data,
            id=f"bounty-{bounty_id}",
            task_queue=config.TEMPORAL_TASK_QUEUE
        )
        
        logger.info(f"Started workflow bounty-{bounty_id}")
        return handle.id
    
    async def get_workflow_result(self, workflow_id: str, timeout_seconds: int = 3600) -> dict:
        """Wait for workflow result."""
        client = await self.connect()
        
        handle = client.get_workflow_handle(workflow_id)
        result = await handle.result()
        return result
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
        client = await self.connect()
        
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        return True


temporal_client = MercenaryTemporalClient()
