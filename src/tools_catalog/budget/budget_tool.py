import json
from typing import Optional, Dict, Any

from src.plugins.base import Tool, ToolContext
from src.shared.budget.tracker import budget_tracker
from src.shared.budget.pricing import pricing_service
from src.shared.budget.notifier import BudgetNotifier

_budget_notifier = BudgetNotifier()


class BudgetTool(Tool):
    type = "observability"
    name = "budget"
    description = "Track token usage and budget for LLM providers"
    node = "both"
    
    def initialize(self, config: dict) -> None:
        self.config = config
    
    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "budget_status",
                    "description": "Get current budget status for providers and models",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": "Provider name (openrouter, google, anthropic) or 'all'",
                                "enum": ["openrouter", "google", "anthropic", "all"]
                            },
                            "model_id": {
                                "type": "string",
                                "description": "Optional model ID to get model-specific stats"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_set_provider",
                    "description": "Set budget limit for a provider",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": "Provider name",
                                "enum": ["openrouter", "google", "anthropic"]
                            },
                            "limit_usd": {
                                "type": "number",
                                "description": "Budget limit in USD"
                            },
                            "threshold_pct": {
                                "type": "number",
                                "description": "Alert threshold (0.0-1.0), default 0.80",
                                "default": 0.80
                            },
                            "alert_interval": {
                                "type": "integer",
                                "description": "Alert every N tasks when over threshold",
                                "default": 5
                            }
                        },
                        "required": ["provider", "limit_usd"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_set_model",
                    "description": "Set budget limit for a specific model",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {"type": "string"},
                            "model_id": {"type": "string"},
                            "limit_usd": {"type": "number"}
                        },
                        "required": ["provider", "model_id", "limit_usd"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_set_pricing",
                    "description": "Override pricing for a model",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {"type": "string"},
                            "model_id": {"type": "string"},
                            "input_price_per_1m": {
                                "type": "number",
                                "description": "Price per 1M input tokens in USD"
                            },
                            "output_price_per_1m": {
                                "type": "number",
                                "description": "Price per 1M output tokens in USD"
                            },
                            "notes": {"type": "string"}
                        },
                        "required": ["provider", "model_id", "input_price_per_1m", "output_price_per_1m"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_pull",
                    "description": "Pull balance from provider API (OpenRouter only)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "enum": ["openrouter"]
                            }
                        },
                        "required": ["provider"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_pipeline_stats",
                    "description": "Get token usage by pipeline stage",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "Number of days to analyze",
                                "default": 7
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "budget_history",
                    "description": "Get usage history",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {"type": "string"},
                            "days": {"type": "integer", "default": 7},
                            "limit": {"type": "integer", "default": 20}
                        }
                    }
                }
            }
        ]
    
    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        if tool_name == "budget_status":
            return await self._budget_status(args)
        elif tool_name == "budget_set_provider":
            return await self._budget_set_provider(args)
        elif tool_name == "budget_set_model":
            return await self._budget_set_model(args)
        elif tool_name == "budget_set_pricing":
            return await self._budget_set_pricing(args)
        elif tool_name == "budget_pull":
            return await self._budget_pull(args)
        elif tool_name == "budget_pipeline_stats":
            return await self._budget_pipeline_stats(args)
        elif tool_name == "budget_history":
            return await self._budget_history(args)
        else:
            return f"Unknown budget tool: {tool_name}"
    
    async def _budget_status(self, args: dict) -> str:
        provider = args.get("provider")
        model_id = args.get("model_id")
        
        if provider == "all":
            provider = None
        
        status = await budget_tracker.get_status(provider, model_id)
        
        if "error" in status:
            return f"Error: {status['error']}"
        
        return _budget_notifier.format_status_output(status)
    
    async def _budget_set_provider(self, args: dict) -> str:
        provider = args["provider"]
        limit = args["limit_usd"]
        threshold = args.get("threshold_pct", 0.80)
        alert_interval = args.get("alert_interval", 5)
        
        success = await budget_tracker.set_provider_budget(
            provider, limit, threshold, alert_interval
        )
        
        if success:
            return f"✅ Budget set for {provider}:\n   Limit: ${limit:.2f}\n   Threshold: {threshold*100:.0f}%\n   Alert interval: every {alert_interval} tasks"
        else:
            return f"❌ Failed to set budget for {provider}"
    
    async def _budget_set_model(self, args: dict) -> str:
        provider = args["provider"]
        model_id = args["model_id"]
        limit = args["limit_usd"]
        
        if budget_tracker.redis_client:
            await budget_tracker.redis_client.set(
                f"budget:model:{provider}:{model_id}:limit",
                str(limit)
            )
            return f"✅ Budget set for {provider}/{model_id}: ${limit:.2f}"
        else:
            return "❌ Redis not available"
    
    async def _budget_set_pricing(self, args: dict) -> str:
        provider = args["provider"]
        model_id = args["model_id"]
        input_price = args["input_price_per_1m"]
        output_price = args["output_price_per_1m"]
        notes = args.get("notes")
        
        if budget_tracker.db_pool:
            from decimal import Decimal
            success = await pricing_service.set_model_pricing(
                budget_tracker.db_pool,
                provider,
                model_id,
                Decimal(str(input_price)),
                Decimal(str(output_price)),
                notes=notes
            )
            if success:
                return f"✅ Pricing set for {provider}/{model_id}:\n   Input: ${input_price:.4f}/1M tokens\n   Output: ${output_price:.4f}/1M tokens"
        
        return f"❌ Failed to set pricing (DB not available)"
    
    async def _budget_pull(self, args: dict) -> str:
        provider = args["provider"]
        
        if provider == "openrouter":
            from src.shared.budget.provider_apis import OpenRouterClient
            client = OpenRouterClient()
            
            key_info = await client.get_key_info()
            if key_info:
                limit = key_info.get("limit", 0)
                remaining = key_info.get("limit_remaining", 0)
                spent = limit - remaining
                
                if budget_tracker.redis_client:
                    await budget_tracker.redis_client.set("budget:provider:openrouter:limit", str(limit))
                    await budget_tracker.redis_client.set("budget:provider:openrouter:spent", str(spent))
                    await budget_tracker.redis_client.set("budget:provider:openrouter:balance", str(remaining))
                
                return f"✅ OpenRouter balance synced:\n   Limit: ${limit:.2f}\n   Spent: ${spent:.2f}\n   Remaining: ${remaining:.2f}"
            else:
                return "❌ Failed to get OpenRouter balance"
        
        return f"❌ Provider {provider} does not support balance pull"
    
    async def _budget_pipeline_stats(self, args: dict) -> str:
        days = args.get("days", 7)
        stats = await budget_tracker.get_pipeline_stats(days)
        return _budget_notifier.format_pipeline_stats(stats)
    
    async def _budget_history(self, args: dict) -> str:
        provider = args.get("provider")
        days = args.get("days", 7)
        limit = args.get("limit", 20)
        
        if not budget_tracker.db_pool:
            return "❌ Database not available"
        
        try:
            async with budget_tracker.db_pool.acquire() as conn:
                query = """
                    SELECT task_id, provider, model_id, pipeline_stage, 
                           total_tokens, cost_usd, created_at
                    FROM task_usage
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """
                params = [days]
                
                if provider:
                    query += " AND provider = $2"
                    params.append(provider)
                
                query += f" ORDER BY created_at DESC LIMIT {limit}"
                
                rows = await conn.fetch(query, *params)
                
                lines = [f"📋 Usage History (Last {days} days)", ""]
                for row in rows:
                    lines.append(
                        f"• {row['created_at'].strftime('%Y-%m-%d %H:%M')} | "
                        f"{row['provider']}/{row['model_id'].split('/')[-1]} | "
                        f"{row['total_tokens']} tokens | ${row['cost_usd']:.4f}"
                    )
                
                return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"


tool_class = BudgetTool
