"""
Seed default budget configuration

Run with: python scripts/seed_budget_config.py
"""

import asyncio
import asyncpg
import os
import json
from decimal import Decimal


SEED_BUDGET_SETTINGS = [
    {"setting_key": "default_threshold_pct", "setting_value": json.dumps(0.80), "description": "Alert threshold (fraction of budget)"},
    {"setting_key": "alert_interval_tasks", "setting_value": json.dumps(5), "description": "Alert every N tasks when over threshold"},
    {"setting_key": "sync_interval_seconds", "setting_value": json.dumps(60), "description": "How often to sync Redis to Postgres"},
    {"setting_key": "safety_margin_pct", "setting_value": json.dumps(0.25), "description": "Buffer added to estimates (future use)"},
]

SEED_PROVIDER_BUDGETS = [
    {"provider": "openrouter", "budget_limit_usd": Decimal("20.00"), "pull_from_api": True, "api_key_env": "OPENROUTER_API_KEY"},
    {"provider": "google", "budget_limit_usd": Decimal("10.00"), "pull_from_api": False},
    {"provider": "anthropic", "budget_limit_usd": Decimal("5.00"), "pull_from_api": False},
]

SEED_MODEL_PRICING = [
    {"provider": "openrouter", "model_id": "zhipuai/glm-5-pro", "input_price_per_1m": Decimal("0.50"), "output_price_per_1m": Decimal("0.50")},
    {"provider": "openrouter", "model_id": "anthropic/claude-opus-4-5", "input_price_per_1m": Decimal("15.00"), "output_price_per_1m": Decimal("75.00")},
    {"provider": "openrouter", "model_id": "anthropic/claude-sonnet-4-6", "input_price_per_1m": Decimal("3.00"), "output_price_per_1m": Decimal("15.00")},
    {"provider": "openrouter", "model_id": "anthropic/claude-3.5-sonnet", "input_price_per_1m": Decimal("3.00"), "output_price_per_1m": Decimal("15.00")},
    {"provider": "openrouter", "model_id": "openai/gpt-4o", "input_price_per_1m": Decimal("2.50"), "output_price_per_1m": Decimal("10.00")},
    {"provider": "openrouter", "model_id": "openai/gpt-4-turbo", "input_price_per_1m": Decimal("10.00"), "output_price_per_1m": Decimal("30.00")},
    {"provider": "openrouter", "model_id": "google/gemini-2.5-flash", "input_price_per_1m": Decimal("0.15"), "output_price_per_1m": Decimal("0.60")},
    {"provider": "openrouter", "model_id": "google/gemini-2.5-flash-lite", "input_price_per_1m": Decimal("0.075"), "output_price_per_1m": Decimal("0.30")},
    {"provider": "openrouter", "model_id": "google/gemini-2.0-flash", "input_price_per_1m": Decimal("0.10"), "output_price_per_1m": Decimal("0.40")},
    {"provider": "google", "model_id": "gemini-2.5-flash", "input_price_per_1m": Decimal("0.15"), "output_price_per_1m": Decimal("0.60")},
    {"provider": "google", "model_id": "gemini-2.5-flash-lite", "input_price_per_1m": Decimal("0.075"), "output_price_per_1m": Decimal("0.30")},
    {"provider": "google", "model_id": "gemini-2.0-flash", "input_price_per_1m": Decimal("0.10"), "output_price_per_1m": Decimal("0.40")},
    {"provider": "google", "model_id": "gemini-2.5-pro", "input_price_per_1m": Decimal("1.25"), "output_price_per_1m": Decimal("10.00")},
    {"provider": "anthropic", "model_id": "claude-opus-4-5", "input_price_per_1m": Decimal("15.00"), "output_price_per_1m": Decimal("75.00")},
    {"provider": "anthropic", "model_id": "claude-sonnet-4-6", "input_price_per_1m": Decimal("3.00"), "output_price_per_1m": Decimal("15.00")},
    {"provider": "anthropic", "model_id": "claude-3-5-sonnet-20241022", "input_price_per_1m": Decimal("3.00"), "output_price_per_1m": Decimal("15.00")},
]


async def seed_budget_config(database_url: str):
    print("Seeding budget configuration...")
    
    conn = await asyncpg.connect(database_url)
    
    try:
        # Seed budget settings
        for setting in SEED_BUDGET_SETTINGS:
            await conn.execute(
                """
                INSERT INTO budget_settings (setting_key, setting_value, description)
                VALUES ($1, $2, $3)
                ON CONFLICT (setting_key) DO UPDATE SET
                    setting_value = $2,
                    description = $3,
                    updated_at = NOW()
                """,
                setting["setting_key"],
                setting["setting_value"],
                setting["description"]
            )
        print(f"✅ Seeded {len(SEED_BUDGET_SETTINGS)} budget settings")
        
        # Seed provider budgets
        for pb in SEED_PROVIDER_BUDGETS:
            await conn.execute(
                """
                INSERT INTO provider_budgets 
                (provider, budget_limit_usd, pull_from_api, api_key_env)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (provider) DO UPDATE SET
                    budget_limit_usd = $2,
                    pull_from_api = $3,
                    api_key_env = $4,
                    updated_at = NOW()
                """,
                pb["provider"],
                pb["budget_limit_usd"],
                pb["pull_from_api"],
                pb.get("api_key_env")
            )
        print(f"✅ Seeded {len(SEED_PROVIDER_BUDGETS)} provider budgets")
        
        # Seed model pricing
        for mp in SEED_MODEL_PRICING:
            await conn.execute(
                """
                INSERT INTO model_pricing 
                (provider, model_id, input_price_per_1m, output_price_per_1m, source)
                VALUES ($1, $2, $3, $4, 'hardcoded')
                ON CONFLICT (provider, model_id, effective_date) DO UPDATE SET
                    input_price_per_1m = $3,
                    output_price_per_1m = $4,
                    source = 'hardcoded',
                    updated_at = NOW()
                """,
                mp["provider"],
                mp["model_id"],
                mp["input_price_per_1m"],
                mp["output_price_per_1m"]
            )
        print(f"✅ Seeded {len(SEED_MODEL_PRICING)} model pricing entries")
        
        print("\n🎉 Budget configuration seeded successfully!")
        
    except Exception as e:
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "postgresql://temporal:temporal@localhost:5432/orchestrator")
    asyncio.run(seed_budget_config(db_url))
