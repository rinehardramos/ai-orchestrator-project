"""
Spreadsheet Storage Client - Hybrid Postgres+Qdrant storage for spreadsheets.

Provides:
- Structured storage in Postgres for querying/filtering
- Vector embeddings in Qdrant for semantic search
- Synchronization between both stores
"""

import os
import json
import uuid
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

from src.shared.spreadsheet_processor import (
    SpreadsheetProcessor, 
    SpreadsheetInfo, 
    RowData,
    process_spreadsheet
)
from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
from src.shared.memory.knowledge_base import KnowledgeBaseClient


@dataclass
class SpreadsheetQueryResult:
    rows: List[Dict[str, Any]]
    total: int
    spreadsheet_info: Optional[Dict[str, Any]] = None


class SpreadsheetStorageClient:
    """
    Hybrid storage client for spreadsheets.
    
    Architecture:
    - Postgres: Structured row/column data, filtering, aggregation
    - Qdrant: Vector embeddings for semantic search
    """
    
    def __init__(
        self,
        database_url: str = None,
        qdrant_url: str = None,
        embedding_client: KnowledgeBaseClient = None
    ):
        self.database_url = database_url or os.environ.get(
            "DATABASE_URL",
            "postgresql://temporal:temporal@localhost:5432/orchestrator"
        )
        self.qdrant_url = qdrant_url or os.environ.get("QDRANT_URL")
        self._pool = None
        self._embedding_client = embedding_client
        self._qdrant_collection = "spreadsheets_v1"
    
    async def _get_pool(self):
        if self._pool is None and ASYNCPG_AVAILABLE:
            self._pool = await asyncpg.create_pool(
                self.database_url, 
                min_size=1, 
                max_size=5
            )
        return self._pool
    
    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    def _get_embedding_client(self) -> KnowledgeBaseClient:
        if self._embedding_client is None:
            self._embedding_client = KnowledgeBaseClient()
        return self._embedding_client
    
    async def store_spreadsheet(
        self,
        file_path: str,
        name: str = None,
        sheet_index: int = 0,
        description: str = None,
        tags: List[str] = None,
        create_embeddings: bool = True,
        created_by: str = None
    ) -> Tuple[str, SpreadsheetInfo]:
        """
        Process and store a spreadsheet file.
        
        Returns (spreadsheet_id, info)
        """
        processor = SpreadsheetProcessor()
        info, rows = processor.parse_file(file_path, sheet_index)
        
        # Override name if provided
        if name:
            info.name = name
        
        pool = await self._get_pool()
        spreadsheet_id = str(uuid.uuid4())
        info.spreadsheet_id = spreadsheet_id
        
        async with pool.acquire() as conn:
            # Insert spreadsheet metadata
            await conn.execute("""
                INSERT INTO spreadsheets (
                    id, name, description, source_path, file_type,
                    sheet_name, sheet_index, row_count, column_count,
                    column_headers, column_types, status, tags, created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'ready', $12, $13)
            """,
                spreadsheet_id,
                info.name,
                description,
                info.source_path,
                info.file_type,
                info.sheet_name,
                info.sheet_index,
                info.row_count,
                info.column_count,
                json.dumps(info.column_headers),
                json.dumps(info.column_types),
                json.dumps(tags or []),
                created_by
            )
            
            # Batch insert rows
            if rows:
                row_records = []
                for row in rows:
                    row_records.append((
                        str(uuid.uuid4()),
                        spreadsheet_id,
                        row.row_index,
                        row.row_hash,
                        json.dumps(row.row_data, default=str)
                    ))
                
                await conn.executemany("""
                    INSERT INTO spreadsheet_rows (
                        id, spreadsheet_id, row_index, row_hash, row_data
                    ) VALUES ($1, $2, $3, $4, $5::jsonb)
                """, row_records)
            
            # Update status
            await conn.execute("""
                UPDATE spreadsheets SET status = 'ready', processed_at = NOW()
                WHERE id = $1
            """, spreadsheet_id)
        
        # Create embeddings if requested
        if create_embeddings and rows:
            await self._create_embeddings(spreadsheet_id, info, rows, processor)
        
        return spreadsheet_id, info
    
    async def _create_embeddings(
        self,
        spreadsheet_id: str,
        info: SpreadsheetInfo,
        rows: List[RowData],
        processor: SpreadsheetProcessor
    ):
        """Create and store vector embeddings for spreadsheet rows."""
        client = self._get_embedding_client()
        collection_name = f"{self._qdrant_collection}"
        
        pool = await self._get_pool()
        embedding_records = []
        
        for row in rows:
            text = processor.generate_row_text(row, info.column_headers)
            vector = client.embed_text(text)
            point_id = str(uuid.uuid4())
            
            entry = MemoryEntry(
                id=point_id,
                content=text,
                metadata={
                    "spreadsheet_id": spreadsheet_id,
                    "row_index": row.row_index,
                    "spreadsheet_name": info.name,
                    "source_path": info.source_path,
                    "type": "spreadsheet_row"
                }
            )
            
            client.store.store_l2(collection_name, entry, vector)
            
            embedding_records.append((
                str(uuid.uuid4()),
                spreadsheet_id,
                "row",
                str(uuid.uuid4()) if hasattr(row, 'id') else None,
                point_id,
                collection_name,
                client._embed_model,
                client._embed_dim,
                text
            ))
        
        # Store embedding references in Postgres
        async with pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO spreadsheet_embeddings (
                    id, spreadsheet_id, entity_type, entity_id,
                    qdrant_point_id, qdrant_collection,
                    embedding_model, embedding_dim, embedded_content
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, embedding_records)
            
            await conn.execute("""
                UPDATE spreadsheets 
                SET qdrant_collection = $1
                WHERE id = $2
            """, collection_name, spreadsheet_id)
    
    async def search_semantic(
        self,
        query: str,
        limit: int = 10,
        spreadsheet_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across spreadsheet rows using vector similarity.
        """
        client = self._get_embedding_client()
        query_vector = client.embed_text(query)
        
        filter_conditions = None
        if spreadsheet_id:
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            filter_conditions = Filter(
                must=[
                    FieldCondition(
                        key="spreadsheet_id",
                        match=MatchValue(value=spreadsheet_id)
                    )
                ]
            )
        
        results = client.store.query_l2(
            self._qdrant_collection,
            query_vector,
            limit=limit
        )
        
        rows = []
        for r in results:
            payload = r.payload or {}
            rows.append({
                "score": r.score,
                "row_index": payload.get("row_index"),
                "spreadsheet_id": payload.get("spreadsheet_id"),
                "spreadsheet_name": payload.get("spreadsheet_name"),
                "content": payload.get("content")
            })
        
        return rows
    
    async def query_rows(
        self,
        spreadsheet_id: str,
        filters: Dict[str, Any] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "row_index"
    ) -> SpreadsheetQueryResult:
        """
        Query rows from a spreadsheet with optional filters.
        
        Filters are applied as JSONB path queries.
        Example: {"column_name": {"eq": "value"}}
        """
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            # Get spreadsheet info
            info_row = await conn.fetchrow("""
                SELECT * FROM spreadsheets WHERE id = $1
            """, spreadsheet_id)
            
            if not info_row:
                return SpreadsheetQueryResult(rows=[], total=0)
            
            # Build query
            where_clauses = ["spreadsheet_id = $1"]
            params = [spreadsheet_id]
            param_idx = 2
            
            if filters:
                for col, condition in filters.items():
                    if isinstance(condition, dict):
                        op = list(condition.keys())[0]
                        val = condition[op]
                        
                        if op == "eq":
                            where_clauses.append(f"row_data->>'{col}' = ${param_idx}")
                            params.append(str(val))
                            param_idx += 1
                        elif op == "contains":
                            where_clauses.append(f"row_data->>'{col}' LIKE ${param_idx}")
                            params.append(f"%{val}%")
                            param_idx += 1
                        elif op == "gt":
                            where_clauses.append(f"(row_data->>'{col}')::numeric > ${param_idx}")
                            params.append(float(val))
                            param_idx += 1
                        elif op == "lt":
                            where_clauses.append(f"(row_data->>'{col}')::numeric < ${param_idx}")
                            params.append(float(val))
                            param_idx += 1
                    else:
                        where_clauses.append(f"row_data->>'{col}' = ${param_idx}")
                        params.append(str(condition))
                        param_idx += 1
            
            where_sql = " AND ".join(where_clauses)
            
            # Get total count
            count_sql = f"SELECT COUNT(*) FROM spreadsheet_rows WHERE {where_sql}"
            total = await conn.fetchval(count_sql, *params)
            
            # Get rows
            rows_sql = f"""
                SELECT id, row_index, row_data, row_hash, embedding_id
                FROM spreadsheet_rows
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([limit, offset])
            
            rows = await conn.fetch(rows_sql, *params)
            
            return SpreadsheetQueryResult(
                rows=[dict(r) for r in rows],
                total=total,
                spreadsheet_info=dict(info_row)
            )
    
    async def list_spreadsheets(
        self,
        status: str = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List all spreadsheets with optional status filter."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT id, name, source_path, file_type, sheet_name,
                           row_count, column_count, status, created_at
                    FROM spreadsheets
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                """, status, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT id, name, source_path, file_type, sheet_name,
                           row_count, column_count, status, created_at
                    FROM spreadsheets
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                """, limit, offset)
            
            return [dict(r) for r in rows]
    
    async def delete_spreadsheet(self, spreadsheet_id: str) -> bool:
        """Delete a spreadsheet and all associated data."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            # Get Qdrant collection info
            row = await conn.fetchrow("""
                SELECT qdrant_collection FROM spreadsheets WHERE id = $1
            """, spreadsheet_id)
            
            if not row:
                return False
            
            # Delete from Postgres (cascades to rows, cells, embeddings)
            await conn.execute("""
                DELETE FROM spreadsheets WHERE id = $1
            """, spreadsheet_id)
            
            # Note: Qdrant points are not deleted automatically
            # Would need to track point IDs and delete them
        
        return True
    
    async def get_spreadsheet_info(self, spreadsheet_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata about a spreadsheet."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM spreadsheets WHERE id = $1
            """, spreadsheet_id)
            
            return dict(row) if row else None


async def main():
    """Demo/test function."""
    client = SpreadsheetStorageClient()
    
    # List existing spreadsheets
    print("Listing spreadsheets...")
    spreadsheets = await client.list_spreadsheets()
    print(f"Found {len(spreadsheets)} spreadsheets")
    for s in spreadsheets:
        print(f"  - {s['name']}: {s['row_count']} rows")
    
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
