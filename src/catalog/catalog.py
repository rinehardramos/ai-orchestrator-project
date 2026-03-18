from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3
import json
import os
from typing import List

app = FastAPI(title="Task Catalog")

DB_PATH = os.getenv("CATALOG_DB", "catalog.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Ensure table exists
with get_conn() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            definition TEXT NOT NULL
        )
    """)
    conn.commit()

class Template(BaseModel):
    id: str
    name: str
    description: str = ""
    definition: str

@app.post("/templates")
async def create_template(tpl: Template):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO templates (id, name, description, definition) VALUES (?,?,?,?)",
                (tpl.id, tpl.name, tpl.description, tpl.definition),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Template ID already exists")
    return {"status": "created", "id": tpl.id}

@app.get("/templates/{tpl_id}")
async def get_template(tpl_id: str):
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM templates WHERE id = ?", (tpl_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")
        return dict(row)

@app.get("/templates")
async def list_templates():
    with get_conn() as conn:
        cur = conn.execute("SELECT id, name, description FROM templates")
        rows = cur.fetchall()
        return [dict(row) for row in rows]

@app.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: str):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM templates WHERE id = ?", (tpl_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted", "id": tpl_id}
