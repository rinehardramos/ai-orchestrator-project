"""
Bounty endpoints.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.mercenary.api.auth import get_current_user
from src.mercenary.db import BountyRepository, TransactionRepository, UserRepository, AgentRepository
from src.mercenary.models import Bounty, BountyStatus, Transaction, TransactionType
from src.mercenary.core.matcher import BountyMatcher
from src.mercenary.config import config

bounties_router = APIRouter(prefix="/bounties", tags=["bounties"])
bounty_repo = BountyRepository()
txn_repo = TransactionRepository()
user_repo = UserRepository()
agent_repo = AgentRepository()
matcher = BountyMatcher()


class BountyCreate(BaseModel):
    title: str
    description: str
    price: float
    duration_minutes: int
    specialization: str = "general"


class BountyResponse(BaseModel):
    id: str
    user_id: str
    title: str
    description: str
    price: float
    duration_minutes: int
    difficulty: str
    specialization: str
    status: str
    claimed_by: Optional[str]
    claimed_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[str]
    user_rating: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True


class BountyRating(BaseModel):
    rating: int
    feedback: Optional[str] = None


@bounties_router.post("", response_model=BountyResponse)
async def create_bounty(request: BountyCreate, user = Depends(get_current_user)):
    if request.price < config.MIN_BOUNTY:
        raise HTTPException(status_code=400, detail=f"Minimum bounty is ${config.MIN_BOUNTY}")
    if request.price > config.MAX_BOUNTY:
        raise HTTPException(status_code=400, detail=f"Maximum bounty is ${config.MAX_BOUNTY}")
    
    balance = user_repo.get_balance(user.id)
    if balance < request.price:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    difficulty = matcher.estimate_difficulty(request.description)
    
    bounty = Bounty(
        user_id=user.id,
        title=request.title,
        description=request.description,
        price=request.price,
        duration_minutes=request.duration_minutes,
        difficulty=difficulty,
        specialization=request.specialization
    )
    
    created = bounty_repo.create(bounty)
    
    txn = Transaction(
        user_id=user.id,
        bounty_id=created.id,
        amount=-request.price,
        transaction_type=TransactionType.ESCROW
    )
    txn_repo.create(txn)
    
    agent, score = matcher.find_best_agent(created)
    
    if agent:
        bounty_repo.claim(created.id, agent.nickname)
        
        txn2 = Transaction(
            user_id=user.id,
            bounty_id=created.id,
            agent_nickname=agent.nickname,
            amount=request.price * (1 - config.PLATFORM_FEE_PERCENT / 100),
            transaction_type=TransactionType.RELEASE
        )
        txn_repo.create(txn2)
        
        created = bounty_repo.get_by_id(created.id)
    
    return BountyResponse(
        id=created.id,
        user_id=created.user_id,
        title=created.title,
        description=created.description,
        price=created.price,
        duration_minutes=created.duration_minutes,
        difficulty=created.difficulty,
        specialization=created.specialization,
        status=created.status.value,
        claimed_by=created.claimed_by,
        claimed_at=created.claimed_at,
        completed_at=created.completed_at,
        result=created.result,
        user_rating=created.user_rating,
        created_at=created.created_at
    )


@bounties_router.get("", response_model=List[BountyResponse])
async def list_bounties(status: Optional[str] = None, user = Depends(get_current_user)):
    bounties = bounty_repo.get_by_user(user.id, status)
    return [
        BountyResponse(
            id=b.id,
            user_id=b.user_id,
            title=b.title,
            description=b.description,
            price=b.price,
            duration_minutes=b.duration_minutes,
            difficulty=b.difficulty,
            specialization=b.specialization,
            status=b.status.value,
            claimed_by=b.claimed_by,
            claimed_at=b.claimed_at,
            completed_at=b.completed_at,
            result=b.result,
            user_rating=b.user_rating,
            created_at=b.created_at
        )
        for b in bounties
    ]


@bounties_router.get("/{bounty_id}", response_model=BountyResponse)
async def get_bounty(bounty_id: str, user = Depends(get_current_user)):
    bounty = bounty_repo.get_by_id(bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    
    if bounty.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return BountyResponse(
        id=bounty.id,
        user_id=bounty.user_id,
        title=bounty.title,
        description=bounty.description,
        price=bounty.price,
        duration_minutes=bounty.duration_minutes,
        difficulty=bounty.difficulty,
        specialization=bounty.specialization,
        status=bounty.status.value,
        claimed_by=bounty.claimed_by,
        claimed_at=bounty.claimed_at,
        completed_at=bounty.completed_at,
        result=bounty.result,
        user_rating=bounty.user_rating,
        created_at=bounty.created_at
    )


@bounties_router.post("/{bounty_id}/rate", response_model=BountyResponse)
async def rate_bounty(bounty_id: str, request: BountyRating, user = Depends(get_current_user)):
    bounty = bounty_repo.get_by_id(bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    
    if bounty.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if bounty.status != BountyStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only rate completed bounties")
    
    if request.rating < 1 or request.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")
    
    updated = bounty_repo.rate(bounty_id, request.rating, request.feedback)
    
    if bounty.claimed_by:
        success = request.rating >= 3
        agent_repo.update_stats(
            nickname=bounty.claimed_by,
            success=success,
            earned=bounty.price * (1 - config.PLATFORM_FEE_PERCENT / 100) if success else 0
        )
    
    return BountyResponse(
        id=updated.id,
        user_id=updated.user_id,
        title=updated.title,
        description=updated.description,
        price=updated.price,
        duration_minutes=updated.duration_minutes,
        difficulty=updated.difficulty,
        specialization=updated.specialization,
        status=updated.status.value,
        claimed_by=updated.claimed_by,
        claimed_at=updated.claimed_at,
        completed_at=updated.completed_at,
        result=updated.result,
        user_rating=updated.user_rating,
        created_at=updated.created_at
    )


@bounties_router.delete("/{bounty_id}")
async def cancel_bounty(bounty_id: str, user = Depends(get_current_user)):
    bounty = bounty_repo.get_by_id(bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    
    if bounty.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if bounty.status != BountyStatus.OPEN:
        raise HTTPException(status_code=400, detail="Can only cancel open bounties")
    
    bounty_repo.update_status(bounty_id, BountyStatus.CANCELLED)
    
    txn = Transaction(
        user_id=user.id,
        bounty_id=bounty_id,
        amount=bounty.price,
        transaction_type=TransactionType.REFUND
    )
    txn_repo.create(txn)
    
    return {"status": "cancelled"}
