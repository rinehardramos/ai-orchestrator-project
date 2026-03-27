"""
Mercenary database models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import uuid


class BountyStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TransactionType(str, Enum):
    DEPOSIT = "deposit"
    ESCROW = "escrow"
    RELEASE = "release"
    REFUND = "refund"
    FEE = "fee"
    WITHDRAWAL = "withdrawal"


@dataclass
class User:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    password_hash: str = ""
    display_name: Optional[str] = None
    balance: float = 0.0
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Agent:
    nickname: str = ""
    model_id: str = ""
    provider: str = ""
    specialization: str = "general"
    personality: str = ""
    reputation_score: float = 0.50
    tasks_completed: int = 0
    success_rate: float = 0.0
    avg_completion_time: Optional[int] = None
    cost_per_task: float = 0.0
    is_available: bool = True
    total_earnings: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Bounty:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    title: str = ""
    description: str = ""
    price: float = 0.0
    duration_minutes: int = 60
    difficulty: str = "medium"
    specialization: str = "general"
    status: BountyStatus = BountyStatus.OPEN
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    artifacts: Optional[dict] = None
    user_rating: Optional[int] = None
    user_feedback: Optional[str] = None
    workflow_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Transaction:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    bounty_id: Optional[str] = None
    agent_nickname: Optional[str] = None
    amount: float = 0.0
    transaction_type: TransactionType = TransactionType.DEPOSIT
    status: str = "pending"
    stripe_payment_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentPerformance:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_nickname: str = ""
    bounty_id: str = ""
    task_difficulty: str = "medium"
    completion_time: Optional[int] = None
    user_rating: Optional[int] = None
    user_feedback: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
