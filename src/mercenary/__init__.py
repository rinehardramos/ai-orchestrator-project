"""
Mercenary Marketplace - Bounty-based AI agent platform.

Submodules (independent repositories):
- src/mercenary/web  → https://github.com/rinehardramos/mercenary-web (Vercel)
- src/mercenary/api  → https://github.com/rinehardramos/mercenary-api (Railway)

Database: Supabase (PostgreSQL)

The mercenary service connects to this core orchestrator via internal API
when submitting tasks for execution.
"""

__all__ = ["web", "api"]

