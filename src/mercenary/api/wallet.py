"""
Wallet endpoints.
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.mercenary.api.auth import get_current_user
from src.mercenary.db import UserRepository, TransactionRepository
from src.mercenary.models import Transaction, TransactionType

wallet_router = APIRouter(prefix="/wallet", tags=["wallet"])
user_repo = UserRepository()
txn_repo = TransactionRepository()


class BalanceResponse(BaseModel):
    balance: float
    pending: float


class DepositRequest(BaseModel):
    amount: float


class TransactionResponse(BaseModel):
    id: str
    amount: float
    transaction_type: str
    status: str
    created_at: datetime


@wallet_router.get("/balance", response_model=BalanceResponse)
async def get_balance(user = Depends(get_current_user)):
    balance = user_repo.get_balance(user.id)
    return BalanceResponse(balance=balance, pending=0.0)


@wallet_router.get("/transactions", response_model=List[TransactionResponse])
async def list_transactions(user = Depends(get_current_user)):
    txns = txn_repo.get_by_user(user.id)
    return [
        TransactionResponse(
            id=t.id,
            amount=t.amount,
            transaction_type=t.transaction_type.value,
            status=t.status,
            created_at=t.created_at
        )
        for t in txns
    ]


@wallet_router.post("/deposit")
async def create_deposit(request: DepositRequest, user = Depends(get_current_user)):
    if request.amount < 5.0:
        raise HTTPException(status_code=400, detail="Minimum deposit is $5.00")
    
    txn = Transaction(
        user_id=user.id,
        amount=request.amount,
        transaction_type=TransactionType.DEPOSIT,
        status="pending"
    )
    created = txn_repo.create(txn)
    
    return {
        "transaction_id": created.id,
        "amount": request.amount,
        "status": "pending",
        "message": "In production, this would return a Stripe checkout URL"
    }
