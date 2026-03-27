"""
Migration: Add Budget Tracking Tables

Run with: python scripts/migrations/001_add_budget_tables.py
"""

import asyncio
import asyncpg


MIGRATION_SQL = """
-- ═══════════════════════════════════════════════════════════════
-- CONFIGURATION TABLES (User-editable settings)
-- ═══════════════════════════════════════════════════════════════

-- Global budget settings
CREATE TABLE IF NOT EXISTS budget_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value JSONB NOT NULL,
    description TEXT,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Provider budgets (user can edit current_balance, budget_limit)
CREATE TABLE IF NOT EXISTS provider_budgets (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) UNIQUE NOT NULL,
    budget_limit_usd DECIMAL(10,4) NOT NULL,
    current_balance_usd DECIMAL(10,4),
    threshold_pct DECIMAL(3,2) DEFAULT 0.80,
    alert_interval_tasks INT DEFAULT 5,
    pull_from_api BOOLEAN DEFAULT false,
    api_key_env VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(100)
);

-- Model pricing (user can edit/override)
CREATE TABLE IF NOT EXISTS model_pricing (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    model_id VARCHAR(100) NOT NULL,
    input_price_per_1m DECIMAL(10,6) NOT NULL,
    output_price_per_1m DECIMAL(10,6) NOT NULL,
    is_override BOOLEAN DEFAULT false,
    source VARCHAR(50) DEFAULT 'hardcoded',
    effective_date DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(100),
    UNIQUE(provider, model_id, effective_date)
);

-- ═══════════════════════════════════════════════════════════════
-- USAGE TRACKING TABLES (System-populated)
-- ═══════════════════════════════════════════════════════════════

-- Task usage (every LLM call, with pipeline stage tracking)
CREATE TABLE IF NOT EXISTS task_usage (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL,
    workflow_id VARCHAR(100),
    step_id VARCHAR(100),
    pipeline_stage VARCHAR(50),
    provider VARCHAR(50) NOT NULL,
    model_id VARCHAR(100) NOT NULL,
    prompt_tokens INT NOT NULL,
    completion_tokens INT NOT NULL,
    total_tokens INT NOT NULL,
    cost_usd DECIMAL(10,6) NOT NULL,
    task_type VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for pipeline analysis
CREATE INDEX IF NOT EXISTS idx_task_usage_pipeline_stage ON task_usage(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_task_usage_provider_model ON task_usage(provider, model_id);
CREATE INDEX IF NOT EXISTS idx_task_usage_created_at ON task_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_task_usage_task_id ON task_usage(task_id);

-- Daily summary (aggregated for reports and optimization)
CREATE TABLE IF NOT EXISTS usage_daily_summary (
    id SERIAL PRIMARY KEY,
    summary_date DATE NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model_id VARCHAR(100),
    pipeline_stage VARCHAR(50),
    total_tasks INT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,
    prompt_tokens BIGINT DEFAULT 0,
    completion_tokens BIGINT DEFAULT 0,
    total_cost_usd DECIMAL(10,4) DEFAULT 0,
    avg_tokens_per_task DECIMAL(10,2),
    avg_cost_per_task DECIMAL(10,6),
    UNIQUE(summary_date, provider, model_id, pipeline_stage)
);

-- ═══════════════════════════════════════════════════════════════
-- FUTURE USE: ESTIMATION & OPTIMIZATION
-- ═══════════════════════════════════════════════════════════════

-- Historical task patterns (for estimation)
CREATE TABLE IF NOT EXISTS task_patterns (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    task_complexity VARCHAR(20),
    avg_steps INT,
    avg_total_tokens BIGINT,
    avg_cost_usd DECIMAL(10,6),
    sample_count INT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(task_type, task_complexity)
);

-- Pipeline stage costs (for optimization insights)
CREATE TABLE IF NOT EXISTS pipeline_stage_stats (
    id SERIAL PRIMARY KEY,
    pipeline_stage VARCHAR(50) UNIQUE NOT NULL,
    avg_tokens_per_occurrence DECIMAL(10,2),
    avg_cost_per_occurrence DECIMAL(10,6),
    frequency_per_task DECIMAL(5,2),
    total_occurrences BIGINT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW()
);
"""


async def run_migration(database_url: str):
    print("Running migration: Add budget tables...")
    
    conn = await asyncpg.connect(database_url)
    
    try:
        await conn.execute(MIGRATION_SQL)
        print("✅ Migration completed successfully")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    import os
    db_url = os.environ.get("DATABASE_URL", "postgresql://temporal:temporal@localhost:5432/orchestrator")
    asyncio.run(run_migration(db_url))
