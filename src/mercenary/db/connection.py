"""
Database connection for mercenary service.
Isolated from orchestrator core database.
"""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from src.mercenary.config import config


def get_connection():
    """Get database connection."""
    return psycopg2.connect(config.DATABASE_URL)


@contextmanager
def get_db() -> Generator:
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize database tables."""
    with get_db() as conn:
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100),
                balance DECIMAL(10,2) DEFAULT 0.0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                nickname VARCHAR(100) PRIMARY KEY,
                model_id VARCHAR(255) NOT NULL,
                provider VARCHAR(100) NOT NULL,
                specialization VARCHAR(100) DEFAULT 'general',
                personality TEXT,
                reputation_score DECIMAL(3,2) DEFAULT 0.50,
                tasks_completed INT DEFAULT 0,
                success_rate DECIMAL(3,2) DEFAULT 0.0,
                avg_completion_time INT,
                cost_per_task DECIMAL(10,2) DEFAULT 0.0,
                is_available BOOLEAN DEFAULT TRUE,
                total_earnings DECIMAL(10,2) DEFAULT 0.0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bounties (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES users(id),
                title VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                duration_minutes INT NOT NULL,
                difficulty VARCHAR(20) DEFAULT 'medium',
                specialization VARCHAR(100) DEFAULT 'general',
                status VARCHAR(20) DEFAULT 'open',
                claimed_by VARCHAR(100) REFERENCES agents(nickname),
                claimed_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                result TEXT,
                artifacts JSONB,
                user_rating INT CHECK (user_rating >= 1 AND user_rating <= 5),
                user_feedback TEXT,
                workflow_id VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES users(id),
                bounty_id UUID REFERENCES bounties(id),
                agent_nickname VARCHAR(100) REFERENCES agents(nickname),
                amount DECIMAL(10,2) NOT NULL,
                transaction_type VARCHAR(20) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                stripe_payment_id VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_performance (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_nickname VARCHAR(100) REFERENCES agents(nickname),
                bounty_id UUID REFERENCES bounties(id),
                task_difficulty VARCHAR(20),
                completion_time INT,
                user_rating INT,
                user_feedback TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bounties_status ON bounties(status)
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bounties_user ON bounties(user_id)
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)
        """)
        
        print("Mercenary database tables created")


def seed_agents():
    """Seed default agents."""
    from src.mercenary.db.agents import AgentRepository
    
    agents_data = [
        {
            "nickname": "Shadow",
            "model_id": "claude-sonnet-4",
            "provider": "anthropic",
            "specialization": "coding",
            "personality": "A silent professional. Coders fear their efficiency. Never misses a deadline.",
            "cost_per_task": 0.50,
        },
        {
            "nickname": "Viper",
            "model_id": "gemini-2.5-flash",
            "provider": "google",
            "specialization": "research",
            "personality": "Quick and precise. Specializes in data extraction and analysis.",
            "cost_per_task": 0.20,
        },
        {
            "nickname": "Ghost",
            "model_id": "gpt-4o",
            "provider": "openai",
            "specialization": "general",
            "personality": "The versatile operative. Handles any mission with surgical precision.",
            "cost_per_task": 0.35,
        },
        {
            "nickname": "Phantom",
            "model_id": "mistralai/mistral-nemo-instruct-2407",
            "provider": "openrouter",
            "specialization": "writing",
            "personality": "Master of words. Documents, reports, and content creation specialist.",
            "cost_per_task": 0.15,
        },
        {
            "nickname": "Reaper",
            "model_id": "claude-opus-4",
            "provider": "anthropic",
            "specialization": "expert",
            "personality": "The elite. Only takes the hardest missions. Expensive but worth it.",
            "cost_per_task": 1.00,
        },
    ]
    
    repo = AgentRepository()
    
    for agent_data in agents_data:
        try:
            repo.upsert(agent_data)
            print(f"Seeded agent: {agent_data['nickname']}")
        except Exception as e:
            print(f"Failed to seed {agent_data['nickname']}: {e}")
