"""
Mercenary Worker - Processes bounty tasks from Temporal queue.

Isolated from core orchestrator, communicates via internal API.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from src.mercenary.config import config
from src.mercenary.temporal import BountyWorkflow, execute_bounty_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    from temporalio.client import Client
    
    logger.info(f"Connecting to Temporal: {config.TEMPORAL_HOST}")
    logger.info(f"Namespace: {config.TEMPORAL_NAMESPACE}")
    logger.info(f"Task queue: {config.TEMPORAL_TASK_QUEUE}")
    
    client = await Client.connect(
        config.TEMPORAL_HOST,
        namespace=config.TEMPORAL_NAMESPACE
    )
    
    worker = Worker(
        client,
        task_queue=config.TEMPORAL_TASK_QUEUE,
        workflows=[BountyWorkflow],
        activities=[execute_bounty_task],
        workflow_runner=UnsandboxedWorkflowRunner()
    )
    
    logger.info("Mercenary worker started. Listening for bounties...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
