from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import json
import os

DB_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost:5432/dagdb")

def get_conn():
    import psycopg2
    return psycopg2.connect(DB_URL)

def init_db():
    """Run table creation once on startup — not at import time."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dags (
                        id TEXT PRIMARY KEY,
                        definition JSONB NOT NULL
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"[DAG Service] DB init skipped (no connection): {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Task DAG Service", lifespan=lifespan)

class DAG(BaseModel):
    id: str
    definition: dict

@app.post("/dags")
async def create_dag(dag: DAG):
    try:
        import psycopg2
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO dags (id, definition) VALUES (%s, %s)",
                        (dag.id, json.dumps(dag.definition)),
                    )
                    conn.commit()
                except psycopg2.IntegrityError:
                    raise HTTPException(status_code=400, detail="DAG ID already exists")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {e}")
    return {"status": "created", "id": dag.id}

@app.get("/dags/{dag_id}")
async def get_dag(dag_id: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT definition FROM dags WHERE id = %s", (dag_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="DAG not found")
                return {"id": dag_id, "definition": row[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {e}")

@app.delete("/dags/{dag_id}")
async def delete_dag(dag_id: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM dags WHERE id = %s", (dag_id,))
                conn.commit()
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="DAG not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {e}")
    return {"status": "deleted", "id": dag_id}
