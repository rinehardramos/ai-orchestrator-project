"""
Internal API endpoints for service-to-service communication.
Used by Mercenary worker to execute tasks via core orchestrator.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import os

from src.config_db import get_loader

internal_router = APIRouter(prefix="/api/internal", tags=["internal"])

INTERNAL_API_KEY = os.environ.get("CORE_API_KEY", "dev-core-api-key")


class AgentExecuteRequest(BaseModel):
    task: str
    model_id: str
    context: Optional[dict] = None


class AgentExecuteResponse(BaseModel):
    status: str
    summary: str
    artifacts: list


def validate_internal_api_key(api_key: str):
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


@internal_router.post("/execute-agent", response_model=AgentExecuteResponse)
async def execute_agent(
    request: AgentExecuteRequest,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Execute an agent task on behalf of mercenary worker.
    Requires service-to-service API key.
    """
    validate_internal_api_key(x_api_key)
    
    try:
        from src.execution.worker.multi_agent_graph import run_orchestrator
        
        payload = {
            "task_type": "agent",
            "description": request.task,
            "repo_url": "",
            "max_tool_calls": 50,
            "max_cost_usd": 1.0,
            "specialization": "general",
        }
        
        result = await run_orchestrator(payload, request.model_id)
        
        return AgentExecuteResponse(
            status=result.get("status", "completed"),
            summary=result.get("summary", ""),
            artifacts=result.get("artifact_files", [])
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@internal_router.get("/health")
async def internal_health(x_api_key: str = Header(..., alias="X-API-Key")):
    """Health check for internal API."""
    validate_internal_api_key(x_api_key)
    return {"status": "healthy"}
