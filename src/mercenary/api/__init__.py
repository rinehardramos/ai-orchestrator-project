"""
API endpoints for mercenary service.
"""

from src.mercenary.api.auth import auth_router
from src.mercenary.api.bounties import bounties_router
from src.mercenary.api.agents import agents_router
from src.mercenary.api.wallet import wallet_router

__all__ = ["auth_router", "bounties_router", "agents_router", "wallet_router"]
