import os
import json
import logging
import aiohttp
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PricingService:
    _instance = None
    _pricing_cache: Dict[str, Dict] = {}
    _cache_timestamp: Optional[datetime] = None
    _cache_ttl_hours: int = 24
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.db_pool = None
        self.redis_client = None
    
    def set_db_pool(self, pool):
        self.db_pool = pool
    
    def set_redis_client(self, client):
        self.redis_client = client
    
    async def get_model_pricing(
        self, 
        provider: str, 
        model_id: str,
        db_pool=None
    ) -> tuple[Decimal, Decimal]:
        pricing = await self._lookup_pricing(provider, model_id, db_pool)
        return pricing["input"], pricing["output"]
    
    async def _lookup_pricing(
        self, 
        provider: str, 
        model_id: str,
        db_pool=None
    ) -> Dict[str, Decimal]:
        pool = db_pool or self.db_pool
        
        if pool:
            pricing = await self._get_db_pricing(pool, provider, model_id)
            if pricing:
                return pricing
        
        hardcoded = self._get_hardcoded_pricing(provider, model_id)
        if hardcoded:
            return hardcoded
        
        return {"input": Decimal("1.00"), "output": Decimal("1.00")}
    
    async def _get_db_pricing(
        self, 
        pool, 
        provider: str, 
        model_id: str
    ) -> Optional[Dict[str, Decimal]]:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT input_price_per_1m, output_price_per_1m, is_override
                    FROM model_pricing
                    WHERE provider = $1 AND model_id = $2
                    AND (effective_date IS NULL OR effective_date <= CURRENT_DATE)
                    ORDER BY is_override DESC, effective_date DESC
                    LIMIT 1
                    """,
                    provider, model_id
                )
                if row:
                    return {
                        "input": Decimal(str(row["input_price_per_1m"])),
                        "output": Decimal(str(row["output_price_per_1m"])),
                        "is_override": row["is_override"]
                    }
        except Exception as e:
            logger.warning(f"Failed to get pricing from DB: {e}")
        return None
    
    def _get_hardcoded_pricing(
        self, 
        provider: str, 
        model_id: str
    ) -> Optional[Dict[str, Decimal]]:
        pricing_table = {
            "openrouter": {
                "zhipuai/glm-5-pro": {"input": Decimal("0.50"), "output": Decimal("0.50")},
                "anthropic/claude-opus-4-5": {"input": Decimal("15.00"), "output": Decimal("75.00")},
                "anthropic/claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
                "anthropic/claude-3.5-sonnet": {"input": Decimal("3.00"), "output": Decimal("15.00")},
                "openai/gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
                "openai/gpt-4-turbo": {"input": Decimal("10.00"), "output": Decimal("30.00")},
                "google/gemini-2.5-flash": {"input": Decimal("0.15"), "output": Decimal("0.60")},
                "google/gemini-2.5-flash-lite": {"input": Decimal("0.075"), "output": Decimal("0.30")},
                "google/gemini-2.0-flash": {"input": Decimal("0.10"), "output": Decimal("0.40")},
                "google/gemini-pro": {"input": Decimal("0.50"), "output": Decimal("1.50")},
            },
            "google": {
                "gemini-2.5-flash": {"input": Decimal("0.15"), "output": Decimal("0.60")},
                "gemini-2.5-flash-lite": {"input": Decimal("0.075"), "output": Decimal("0.30")},
                "gemini-2.0-flash": {"input": Decimal("0.10"), "output": Decimal("0.40")},
                "gemini-2.5-pro": {"input": Decimal("1.25"), "output": Decimal("10.00")},
                "gemini-pro": {"input": Decimal("0.50"), "output": Decimal("1.50")},
            },
            "anthropic": {
                "claude-opus-4-5": {"input": Decimal("15.00"), "output": Decimal("75.00")},
                "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
                "claude-3-5-sonnet-20241022": {"input": Decimal("3.00"), "output": Decimal("15.00")},
                "claude-3-opus-20240229": {"input": Decimal("15.00"), "output": Decimal("75.00")},
            },
        }
        
        provider_pricing = pricing_table.get(provider, {})
        
        for key, values in provider_pricing.items():
            if key in model_id or model_id in key:
                return values
        
        return provider_pricing.get(model_id)
    
    async def fetch_openrouter_pricing(self, api_key: str) -> Dict[str, Dict]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pricing = {}
                        for model in data.get("data", []):
                            model_id = model.get("id", "")
                            p = model.get("pricing", {})
                            pricing[model_id] = {
                                "input": Decimal(str(p.get("prompt", 0))) * 1000,
                                "output": Decimal(str(p.get("completion", 0))) * 1000,
                                "context_length": model.get("context_length", 0),
                            }
                        self._pricing_cache["openrouter"] = pricing
                        self._cache_timestamp = datetime.utcnow()
                        return pricing
        except Exception as e:
            logger.error(f"Failed to fetch OpenRouter pricing: {e}")
        return {}
    
    async def set_model_pricing(
        self,
        pool,
        provider: str,
        model_id: str,
        input_price: Decimal,
        output_price: Decimal,
        updated_by: str = "system",
        notes: str = None
    ) -> bool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO model_pricing 
                    (provider, model_id, input_price_per_1m, output_price_per_1m, is_override, source, notes, updated_by)
                    VALUES ($1, $2, $3, $4, TRUE, 'user_override', $5, $6)
                    ON CONFLICT (provider, model_id, effective_date) 
                    DO UPDATE SET
                        input_price_per_1m = $3,
                        output_price_per_1m = $4,
                        is_override = TRUE,
                        source = 'user_override',
                        notes = $5,
                        updated_by = $6,
                        updated_at = NOW()
                    """,
                    provider, model_id, input_price, output_price, notes, updated_by
                )
            return True
        except Exception as e:
            logger.error(f"Failed to set model pricing: {e}")
            return False


pricing_service = PricingService()
