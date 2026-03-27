"""
Mercenary service configuration.
All settings loaded from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class MercenaryConfig:
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001
    SECRET_KEY: str = ""
    
    DATABASE_URL: str = ""
    
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "mercenary"
    TEMPORAL_TASK_QUEUE: str = "mercenary-bounties"
    
    CORE_API_URL: str = "http://localhost:8000/api/internal"
    CORE_API_KEY: str = ""
    
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    
    JWT_SECRET_KEY: str = ""
    JWT_EXPIRY_MINUTES: int = 60
    
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60
    
    PLATFORM_FEE_PERCENT: float = 15.0
    MIN_BOUNTY: float = 5.0
    MAX_BOUNTY: float = 1000.0
    
    @classmethod
    def from_env(cls) -> "MercenaryConfig":
        return cls(
            API_HOST=os.environ.get("MERCENARY_API_HOST", "0.0.0.0"),
            API_PORT=int(os.environ.get("PORT", os.environ.get("MERCENARY_API_PORT", "8001"))),
            SECRET_KEY=os.environ.get("MERCENARY_SECRET_KEY", "dev-secret-key"),
            DATABASE_URL=os.environ.get("MERCENARY_DATABASE_URL", "postgresql://mercenary:mercenary@localhost:5433/mercenary_db"),
            TEMPORAL_HOST=os.environ.get("TEMPORAL_HOST_URL", "localhost:7233"),
            TEMPORAL_NAMESPACE=os.environ.get("MERCENARY_TEMPORAL_NAMESPACE", "mercenary"),
            TEMPORAL_TASK_QUEUE=os.environ.get("MERCENARY_TASK_QUEUE", "mercenary-bounties"),
            CORE_API_URL=os.environ.get("CORE_API_URL", "http://localhost:8000/api/internal"),
            CORE_API_KEY=os.environ.get("CORE_API_KEY", "dev-core-api-key"),
            STRIPE_SECRET_KEY=os.environ.get("STRIPE_SECRET_KEY", ""),
            STRIPE_WEBHOOK_SECRET=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            JWT_SECRET_KEY=os.environ.get("MERCENARY_JWT_SECRET", "dev-jwt-secret"),
            JWT_EXPIRY_MINUTES=int(os.environ.get("JWT_EXPIRY_MINUTES", "60")),
            RATE_LIMIT_REQUESTS=int(os.environ.get("RATE_LIMIT_REQUESTS", "100")),
            RATE_LIMIT_WINDOW=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
            PLATFORM_FEE_PERCENT=float(os.environ.get("PLATFORM_FEE_PERCENT", "15.0")),
            MIN_BOUNTY=float(os.environ.get("MIN_BOUNTY", "5.0")),
            MAX_BOUNTY=float(os.environ.get("MAX_BOUNTY", "1000.0")),
        )


config = MercenaryConfig.from_env()
