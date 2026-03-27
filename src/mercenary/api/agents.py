"""
Agent endpoints (read-only for users).
"""

from typing import List
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from src.mercenary.db import AgentRepository

agents_router = APIRouter(prefix="/agents", tags=["agents"])
agent_repo = AgentRepository()


class AgentResponse(BaseModel):
    nickname: str
    model_id: str
    provider: str
    specialization: str
    personality: str
    reputation_score: float
    tasks_completed: int
    success_rate: float
    avg_completion_time: int | None
    cost_per_task: float
    is_available: bool
    created_at: datetime


@agents_router.get("", response_model=List[AgentResponse])
async def list_agents():
    agents = agent_repo.get_all()
    return [
        AgentResponse(
            nickname=a.nickname,
            model_id=a.model_id,
            provider=a.provider,
            specialization=a.specialization,
            personality=a.personality,
            reputation_score=a.reputation_score,
            tasks_completed=a.tasks_completed,
            success_rate=a.success_rate,
            avg_completion_time=a.avg_completion_time,
            cost_per_task=a.cost_per_task,
            is_available=a.is_available,
            created_at=a.created_at
        )
        for a in agents
    ]


@agents_router.get("/{nickname}", response_model=AgentResponse)
async def get_agent(nickname: str):
    agent = agent_repo.get_by_nickname(nickname)
    if not agent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return AgentResponse(
        nickname=agent.nickname,
        model_id=agent.model_id,
        provider=agent.provider,
        specialization=agent.specialization,
        personality=agent.personality,
        reputation_score=agent.reputation_score,
        tasks_completed=agent.tasks_completed,
        success_rate=agent.success_rate,
        avg_completion_time=agent.avg_completion_time,
        cost_per_task=agent.cost_per_task,
        is_available=agent.is_available,
        created_at=agent.created_at
    )
