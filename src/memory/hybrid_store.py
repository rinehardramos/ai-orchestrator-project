import sqlite3
import os
from qdrant_client import QdrantClient
from pydantic import BaseModel

class MemoryEntry(BaseModel):
    id: str
    content: str
    metadata: dict

class HybridMemoryStore:
    def __init__(self, local_db_path="data/memory.db", cloud_url=None, cloud_api_key=None):
        # 1. Local SQLite (Fast/Metadata)
        os.makedirs(os.path.dirname(local_db_path), exist_ok=True)
        self.conn = sqlite3.connect(local_db_path)
        self._init_local_db()
        
        # 2. Cloud Qdrant (LTM/Vector)
        if cloud_url:
            self.qdrant = QdrantClient(url=cloud_url, api_key=cloud_api_key)
        else:
            self.qdrant = None

    def _init_local_db(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_cache (
                id TEXT PRIMARY KEY,
                content TEXT,
                metadata TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def store(self, entry: MemoryEntry):
        # Fast Local Write
        cursor = self.conn.cursor()
        import json
        cursor.execute("INSERT OR REPLACE INTO memory_cache (id, content, metadata) VALUES (?, ?, ?)",
                       (entry.id, entry.content, json.dumps(entry.metadata)))
        self.conn.commit()
        
        # Async Cloud LTM Write (This would typically be a Temporal Activity)
        if self.qdrant:
            pass # Temporal workflow handles actual embedding/storing

    def query_local(self, query_text):
        # Heuristic search for recent context
        cursor = self.conn.cursor()
        cursor.execute("SELECT content FROM memory_cache WHERE content LIKE ? LIMIT 5", (f"%{query_text}%",))
        return cursor.fetchall()
