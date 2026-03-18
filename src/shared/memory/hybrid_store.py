import os
import json
import redis
import boto3
from qdrant_client import QdrantClient
from pydantic import BaseModel

class MemoryEntry(BaseModel):
    id: str
    content: str
    metadata: dict

class HybridMemoryStore:
    def __init__(self, redis_url=None, qdrant_url=None, qdrant_api_key=None, s3_bucket=None, aws_region="us-east-1"):
        # L1: Redis (Fast, Ephemeral State, Langgraph Checkpointing)
        redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.redis = redis.from_url(redis_url)
        
        # L2: Qdrant (Persistent, Semantic Vector Search)
        qdrant_url = qdrant_url or os.environ.get("QDRANT_URL")
        if qdrant_url:
            self.qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            self.qdrant = None

        # L3: AWS S3 (Cold, Archival, Audit Trails)
        self.s3_bucket = s3_bucket or os.environ.get("S3_ARCHIVE_BUCKET")
        if self.s3_bucket:
            self.s3 = boto3.client('s3', region_name=aws_region)
        else:
            self.s3 = None

    def store_l1(self, key: str, value: dict, ttl_seconds: int = 3600):
        """Store transient state in Redis."""
        try:
            self.redis.setex(key, ttl_seconds, json.dumps(value))
        except redis.exceptions.ConnectionError:
            print(f"[L1 Cache] Redis not available, skipping store for {key}")

    def get_l1(self, key: str) -> dict:
        """Retrieve transient state from Redis."""
        try:
            data = self.redis.get(key)
            return json.loads(data) if data else None
        except redis.exceptions.ConnectionError:
            print(f"[L1 Cache] Redis not available, skipping get for {key}")
            return None

    def store_l2(self, collection_name: str, entry: MemoryEntry, vector: list):
        """Store persistent semantic memory in Qdrant."""
        if not self.qdrant:
            return
        
        # Ensure collection exists (basic check)
        try:
            self.qdrant.get_collection(collection_name)
        except Exception:
            from qdrant_client.http.models import Distance, VectorParams
            self.qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=len(vector), distance=Distance.COSINE),
            )
            
        self.qdrant.upsert(
            collection_name=collection_name,
            points=[
                {
                    "id": entry.id,
                    "vector": vector,
                    "payload": {
                        "content": entry.content,
                        **entry.metadata
                    }
                }
            ]
        )

    def query_l2(self, collection_name: str, query_vector: list, limit: int = 5):
        """Semantic search in Qdrant."""
        if not self.qdrant:
            return []
        return self.qdrant.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit
        ).points

    def archive_l3(self, task_id: str, full_state: dict):
        """Archive complete task state/audit trail to S3."""
        if not self.s3 or not self.s3_bucket:
            print(f"L3 Archival skipped (no S3 configured) for task {task_id}")
            return
            
        self.s3.put_object(
            Bucket=self.s3_bucket,
            Key=f"tasks/{task_id}/audit_trail.json",
            Body=json.dumps(full_state),
            ContentType="application/json"
        )
