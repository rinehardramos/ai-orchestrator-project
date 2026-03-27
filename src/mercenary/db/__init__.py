"""
Database repositories.
"""

from src.mercenary.db.connection import get_db
from src.mercenary.models import User, Agent, Bounty, Transaction, AgentPerformance, BountyStatus, TransactionType
from datetime import datetime
from typing import Optional, List


class UserRepository:
    def create(self, email: str, password_hash: str, display_name: str = None) -> User:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO users (email, password_hash, display_name)
                VALUES (%s, %s, %s)
                RETURNING id, email, password_hash, display_name, balance, is_active, created_at, updated_at
                """,
                (email, password_hash, display_name)
            )
            row = cur.fetchone()
            return User(**dict(row))
    
    def get_by_id(self, user_id: str) -> Optional[User]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return User(**dict(row)) if row else None
    
    def get_by_email(self, email: str) -> Optional[User]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return User(**dict(row)) if row else None
    
    def update_balance(self, user_id: str, amount: float) -> User:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE users 
                SET balance = balance + %s, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (amount, user_id)
            )
            row = cur.fetchone()
            return User(**dict(row))
    
    def get_balance(self, user_id: str) -> float:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return float(row["balance"]) if row else 0.0


class AgentRepository:
    def upsert(self, data: dict) -> Agent:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agents (nickname, model_id, provider, specialization, personality, cost_per_task)
                VALUES (%(nickname)s, %(model_id)s, %(provider)s, %(specialization)s, %(personality)s, %(cost_per_task)s)
                ON CONFLICT (nickname) DO UPDATE SET
                    model_id = EXCLUDED.model_id,
                    provider = EXCLUDED.provider,
                    specialization = EXCLUDED.specialization,
                    personality = EXCLUDED.personality,
                    cost_per_task = EXCLUDED.cost_per_task
                RETURNING *
                """,
                data
            )
            row = cur.fetchone()
            return Agent(**dict(row))
    
    def get_all(self, available_only: bool = False) -> List[Agent]:
        with get_db() as conn:
            cur = conn.cursor()
            if available_only:
                cur.execute("SELECT * FROM agents WHERE is_available = TRUE ORDER BY reputation_score DESC")
            else:
                cur.execute("SELECT * FROM agents ORDER BY reputation_score DESC")
            return [Agent(**dict(row)) for row in cur.fetchall()]
    
    def get_by_nickname(self, nickname: str) -> Optional[Agent]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agents WHERE nickname = %s", (nickname,))
            row = cur.fetchone()
            return Agent(**dict(row)) if row else None
    
    def update_stats(self, nickname: str, success: bool, completion_time: int = None, earned: float = 0.0):
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE agents SET
                    tasks_completed = tasks_completed + 1,
                    success_rate = CASE 
                        WHEN tasks_completed = 0 THEN CASE WHEN %s THEN 1.0 ELSE 0.0 END
                        ELSE (success_rate * tasks_completed + CASE WHEN %s THEN 1.0 ELSE 0.0 END) / (tasks_completed + 1)
                    END,
                    avg_completion_time = CASE 
                        WHEN %s IS NULL THEN avg_completion_time
                        WHEN avg_completion_time IS NULL THEN %s
                        ELSE (avg_completion_time * tasks_completed + %s) / (tasks_completed + 1)
                    END,
                    total_earnings = total_earnings + %s,
                    reputation_score = LEAST(1.0, reputation_score + CASE WHEN %s THEN 0.05 ELSE -0.10 END)
                WHERE nickname = %s
                """,
                (success, success, completion_time, completion_time, completion_time, earned, success, nickname)
            )


class BountyRepository:
    def create(self, bounty: Bounty) -> Bounty:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bounties (user_id, title, description, price, duration_minutes, difficulty, specialization)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (bounty.user_id, bounty.title, bounty.description, bounty.price, 
                 bounty.duration_minutes, bounty.difficulty, bounty.specialization)
            )
            row = cur.fetchone()
            return Bounty(**dict(row))
    
    def get_by_id(self, bounty_id: str) -> Optional[Bounty]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bounties WHERE id = %s", (bounty_id,))
            row = cur.fetchone()
            return Bounty(**dict(row)) if row else None
    
    def get_by_user(self, user_id: str, status: str = None) -> List[Bounty]:
        with get_db() as conn:
            cur = conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM bounties WHERE user_id = %s AND status = %s ORDER BY created_at DESC",
                    (user_id, status)
                )
            else:
                cur.execute(
                    "SELECT * FROM bounties WHERE user_id = %s ORDER BY created_at DESC",
                    (user_id,)
                )
            return [Bounty(**dict(row)) for row in cur.fetchall()]
    
    def get_open_bounties(self) -> List[Bounty]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM bounties WHERE status = 'open' ORDER BY price DESC, created_at ASC"
            )
            return [Bounty(**dict(row)) for row in cur.fetchall()]
    
    def claim(self, bounty_id: str, agent_nickname: str) -> Bounty:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE bounties 
                SET status = 'claimed', claimed_by = %s, claimed_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'open'
                RETURNING *
                """,
                (agent_nickname, bounty_id)
            )
            row = cur.fetchone()
            return Bounty(**dict(row)) if row else None
    
    def update_status(self, bounty_id: str, status: BountyStatus, **kwargs) -> Bounty:
        with get_db() as conn:
            cur = conn.cursor()
            
            set_clauses = ["status = %s", "updated_at = NOW()"]
            values = [status.value]
            
            if status == BountyStatus.COMPLETED:
                set_clauses.append("completed_at = NOW()")
            if "result" in kwargs:
                set_clauses.append("result = %s")
                values.append(kwargs["result"])
            if "artifacts" in kwargs:
                set_clauses.append("artifacts = %s")
                values.append(kwargs["artifacts"])
            if "workflow_id" in kwargs:
                set_clauses.append("workflow_id = %s")
                values.append(kwargs["workflow_id"])
            
            values.append(bounty_id)
            
            cur.execute(
                f"UPDATE bounties SET {', '.join(set_clauses)} WHERE id = %s RETURNING *",
                values
            )
            row = cur.fetchone()
            return Bounty(**dict(row)) if row else None
    
    def rate(self, bounty_id: str, rating: int, feedback: str = None) -> Bounty:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE bounties 
                SET user_rating = %s, user_feedback = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (rating, feedback, bounty_id)
            )
            row = cur.fetchone()
            return Bounty(**dict(row)) if row else None


class TransactionRepository:
    def create(self, txn: Transaction) -> Transaction:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO transactions (user_id, bounty_id, agent_nickname, amount, transaction_type, status, stripe_payment_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (txn.user_id, txn.bounty_id, txn.agent_nickname, txn.amount, 
                 txn.transaction_type.value, txn.status, txn.stripe_payment_id)
            )
            row = cur.fetchone()
            return Transaction(**dict(row))
    
    def get_by_user(self, user_id: str) -> List[Transaction]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,)
            )
            return [Transaction(**dict(row)) for row in cur.fetchall()]
    
    def update_status(self, txn_id: str, status: str) -> Transaction:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transactions SET status = %s WHERE id = %s RETURNING *",
                (status, txn_id)
            )
            row = cur.fetchone()
            return Transaction(**dict(row)) if row else None
