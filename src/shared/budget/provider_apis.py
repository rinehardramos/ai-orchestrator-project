import os
import logging
from typing import Optional
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1"
    
    async def get_credits(self) -> Optional[dict]:
        if not self.api_key:
            logger.warning("OpenRouter API key not set")
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/credits",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "total_credits": data.get("data", {}).get("total_credits", 0),
                            "total_usage": data.get("data", {}).get("total_usage", 0),
                        }
                    else:
                        logger.error(f"OpenRouter credits API error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to get OpenRouter credits: {e}")
            return None
    
    async def get_key_info(self) -> Optional[dict]:
        if not self.api_key:
            logger.warning("OpenRouter API key not set")
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/key",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "limit": data.get("data", {}).get("limit"),
                            "limit_remaining": data.get("data", {}).get("limit_remaining"),
                            "usage": data.get("data", {}).get("usage"),
                            "usage_daily": data.get("data", {}).get("usage_daily"),
                            "is_free_tier": data.get("data", {}).get("is_free_tier", False),
                        }
                    else:
                        logger.error(f"OpenRouter key API error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to get OpenRouter key info: {e}")
            return None
    
    async def get_usage_activity(self, date: Optional[str] = None) -> Optional[list]:
        if not self.api_key:
            logger.warning("OpenRouter API key not set")
            return None
        
        try:
            url = f"{self.base_url}/activity"
            if date:
                url += f"?date={date}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", [])
                    else:
                        logger.error(f"OpenRouter activity API error: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to get OpenRouter usage activity: {e}")
            return None
    
    async def sync_balance_to_redis(self, redis_client) -> bool:
        key_info = await self.get_key_info()
        if not key_info:
            return False
        
        try:
            limit = key_info.get("limit") or 0
            remaining = key_info.get("limit_remaining") or 0
            spent = limit - remaining
            
            await redis_client.set("budget:provider:openrouter:limit", str(limit))
            await redis_client.set("budget:provider:openrouter:spent", str(spent))
            await redis_client.set("budget:provider:openrouter:balance", str(remaining))
            
            logger.info(f"Synced OpenRouter balance to Redis: ${remaining:.2f} remaining")
            return True
        except Exception as e:
            logger.error(f"Failed to sync OpenRouter balance to Redis: {e}")
            return False


class GoogleClient:
    def __init__(self):
        pass
    
    async def get_usage(self) -> Optional[dict]:
        return None


class AnthropicClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    
    async def get_usage(self) -> Optional[dict]:
        return None
