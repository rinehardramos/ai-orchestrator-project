"""
Knowledge Store - Document storage and retrieval using Qdrant.

Uses named vectors for dual embedding support:
- Single collection with two named vector spaces: "text" and "code"
- Each document chunk can have one or both embeddings
- Query by specific vector type for optimal retrieval
"""

import os
import sys
import uuid
import shutil
import logging
from datetime import datetime
from typing import Optional, Literal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Filter, FieldCondition, MatchValue, MatchAny, 
    Distance, VectorParams, PointStruct
)
from src.shared.memory.hybrid_store import MemoryEntry
from src.shared.memory.knowledge_base import KnowledgeBaseClient

DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "documents")
logger = logging.getLogger(__name__)


def classify_content_type(text: str, file_type: str = None, category: str = None) -> Literal["text", "code"]:
    """Classify content type for embedding routing.
    
    Args:
        text: Content to classify
        file_type: File extension (e.g., '.py', '.pdf')
        category: Document category (e.g., 'resume', 'code', 'documentation')
    
    Returns: 'text' or 'code'
    """
    code_extensions = {'.py', '.js', '.ts', '.java', '.go', '.rs', '.cpp', '.c', '.h', 
                       '.jsx', '.tsx', '.vue', '.rb', '.php', '.swift', '.kt', '.scala'}
    
    if file_type and file_type.lower() in code_extensions:
        return "code"
    
    if category == "code":
        return "code"
    
    if category in ["resume", "document", "article", "notes"]:
        return "text"
    
    code_indicators = [
        r'```[\w]*',
        r'^\s*(def |class |function |import |export |const |let |var )',
        r'^\s*(if\(|for\(|while\(|try\{|catch\()',
        r'->\s*\w+',
        r'=>\s*\{',
    ]
    
    import re
    matches = sum(1 for pattern in code_indicators if re.search(pattern, text, re.MULTILINE))
    
    return "code" if matches >= 2 else "text"


class KnowledgeStore:
    """Document storage and retrieval using Qdrant with named vectors.
    Single collection with dual named vectors:
    - "text": 768-dim embeddings for general text
    - "code": 3584-dim embeddings for code/technical content
    """
    
    VECTOR_TEXT = "text"
    VECTOR_CODE = "code"
    
    def __init__(self, collection_name: str = None):
        if collection_name is None:
            try:
                from src.config_db import get_loader
                loader = get_loader()
                config = loader.load_namespace("knowledge") or {}
                collection_name = config.get("knowledge_collection", "knowledge_v1")
            except Exception:
                collection_name = "knowledge_v1"
        self.collection_name = collection_name
        self.embedder = KnowledgeBaseClient()
        self.qdrant = self.embedder.store.qdrant
        
        self._load_dual_embedding_config()
        self._ensure_collection()
    
    def _load_dual_embedding_config(self):
        """Load dual embedding config from database."""
        try:
            from src.config_db import get_loader
            loader = get_loader()
            profiles = loader.load_namespace("profiles")
            task_routing = profiles.get("task_routing", {})
            
            self._configs = {}
            
            for embed_type in ["text", "code"]:
                emb_key = f"embeddings_{embed_type}"
                emb_config = task_routing.get(emb_key, {})
                
                if emb_config:
                    self._configs[embed_type] = {
                        "model": emb_config.get("model"),
                        "provider": emb_config.get("provider"),
                        "dim": emb_config.get("dim"),
                    }
                    logger.info(f"KnowledgeStore {embed_type} config: model={emb_config.get('model')}, dim={emb_config.get('dim')}")
            
            if not self._configs:
                raise ValueError("No embedding configs found")
                
        except Exception as e:
            logger.warning(f"Could not load dual embedding config, using defaults: {e}")
            self._configs = {
                "text": {"model": "nomic-embed-text-v1.5", "provider": "lmstudio", "dim": 768},
                "code": {"model": "nomic-embed-code", "provider": "lmstudio", "dim": 3584}
            }
    
    def _get_api_base(self, provider: str) -> str:
        """Get API base URL for provider."""
        if provider in ["lmstudio", "local", "ollama"]:
            # Prefer environment variables
            host = os.environ.get("LMSTUDIO_HOST", os.environ.get("OLLAMA_HOST"))
            port = os.environ.get("LMSTUDIO_PORT", os.environ.get("OLLAMA_PORT", "1234"))
            if host:
                return f"http://{host}:{port}/v1"
            
            # Fallback to settings.yaml
            try:
                from src.config import load_settings
                settings = load_settings()
                lmstudio = settings.get("lmstudio", {})
                host = lmstudio.get("host", "localhost")
                port = lmstudio.get("port", 1234)
                return f"http://{host}:{port}/v1"
            except Exception:
                return "http://localhost:1234/v1"
        return "http://localhost:1234/v1"
    
    def _ensure_collection(self):
        """Create collection with named vectors if it doesn't exist."""
        if not self.qdrant:
            raise RuntimeError("Qdrant not configured. Set QDRANT_URL environment variable.")
        
        try:
            collection = self.qdrant.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' exists with {collection.points_count} points")
            return
        except Exception:
            pass
        
        text_dim = self._configs.get("text", {}).get("dim", 768)
        code_dim = self._configs.get("code", {}).get("dim", 3584)
        
        logger.info(f"Creating Qdrant collection '{self.collection_name}' with named vectors: text={text_dim}, code={code_dim}")
        
        self.qdrant.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                self.VECTOR_TEXT: VectorParams(size=text_dim, distance=Distance.COSINE),
                self.VECTOR_CODE: VectorParams(size=code_dim, distance=Distance.COSINE),
            }
        )
        
        logger.info(f"Collection '{self.collection_name}' created successfully")
    
    def _embed_text(self, text: str, embed_type: Literal["text", "code"]) -> list[float]:
        """Generate embedding using the appropriate model."""
        config = self._configs.get(embed_type, self._configs["text"])
        model = config.get("model")
        provider = config.get("provider")
        api_base = self._get_api_base(provider)
        
        import requests
        resp = requests.post(
            f"{api_base}/embeddings",
            headers={"Authorization": "Bearer lmstudio"},
            json={"model": model, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    
    def ingest_document(
        self,
        chunks: list[dict],
        doc_id: str,
        doc_name: str,
        file_type: str,
        source: str = "cli",
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        file_path: Optional[str] = None
    ) -> int:
        """
        Store document chunks with named vectors.
        
        Each chunk gets both embeddings (text and code) for maximum flexibility.
        Returns number of chunks ingested.
        """
        created_at = datetime.utcnow().isoformat()
        ingested = 0
        
        points = []
        
        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            
            text_to_embed = chunk['text']
            if chunk.get('section_title'):
                text_to_embed = f"{chunk['section_title']}\n{chunk['text']}"
            
            primary_type = classify_content_type(text_to_embed, file_type, category)
            
            text_embedding = self._embed_text(text_to_embed, "text")
            code_embedding = self._embed_text(text_to_embed, "code")
            
            payload = {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "file_type": file_type,
                "source": source,
                "chunk_index": chunk['chunk_index'],
                "chunk_type": chunk.get('chunk_type', 'paragraph'),
                "section_title": chunk.get('section_title'),
                "text": chunk['text'],
                "category": category,
                "tags": tags or [],
                "file_path": file_path,
                "created_at": created_at,
                "primary_type": primary_type,
            }
            
            point = PointStruct(
                id=chunk_id,
                vector={
                    self.VECTOR_TEXT: text_embedding,
                    self.VECTOR_CODE: code_embedding,
                },
                payload=payload
            )
            points.append(point)
            ingested += 1
        
        if points:
            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=points
            )
        
        return ingested
    
    def query(
        self,
        query_text: str,
        limit: int = 5,
        filters: Optional[dict] = None,
        embed_type: Literal["text", "code", "auto"] = "auto",
        search_both: bool = False
    ) -> list[dict]:
        """
        Semantic search using named vectors.
        
        Args:
            query_text: Search query
            limit: Max results
            filters: Metadata filters
            embed_type: Which vector to use ("text", "code", or "auto")
            search_both: Query both vectors and combine results
        
        Returns list of matching chunks with metadata.
        """
        if not self.qdrant:
            return []
        
        if embed_type == "auto":
            embed_type = classify_content_type(query_text)
        
        qdrant_filter = self._build_filter(filters)
        
        if search_both:
            return self._search_both_vectors(query_text, limit, qdrant_filter)
        
        return self._search_single_vector(query_text, embed_type, limit, qdrant_filter)
    
    def _build_filter(self, filters: Optional[dict]) -> Optional[Filter]:
        """Build Qdrant filter from dict."""
        if not filters:
            return None
        
        conditions = []
        
        if filters.get('doc_name'):
            conditions.append(FieldCondition(
                key="doc_name",
                match=MatchValue(value=filters['doc_name'])
            ))
        
        if filters.get('doc_id'):
            conditions.append(FieldCondition(
                key="doc_id",
                match=MatchValue(value=filters['doc_id'])
            ))
        
        if filters.get('category'):
            conditions.append(FieldCondition(
                key="category",
                match=MatchValue(value=filters['category'])
            ))
        
        if filters.get('tags'):
            conditions.append(FieldCondition(
                key="tags",
                match=MatchAny(any=filters['tags'])
            ))
        
        if filters.get('primary_type'):
            conditions.append(FieldCondition(
                key="primary_type",
                match=MatchValue(value=filters['primary_type'])
            ))
        
        return Filter(must=conditions) if conditions else None
    
    def _search_single_vector(
        self,
        query_text: str,
        embed_type: Literal["text", "code"],
        limit: int,
        qdrant_filter: Optional[Filter]
    ) -> list[dict]:
        """Search using a single named vector."""
        vector = self._embed_text(query_text, embed_type)
        vector_name = self.VECTOR_TEXT if embed_type == "text" else self.VECTOR_CODE
        
        try:
            results = self.qdrant.query_points(
                collection_name=self.collection_name,
                query=vector,
                using=vector_name,
                limit=limit,
                query_filter=qdrant_filter
            ).points
        except Exception as e:
            logger.warning(f"Failed to search {vector_name}: {e}")
            return []
        
        return self._format_results(results, embed_type)
    
    def _search_both_vectors(
        self,
        query_text: str,
        limit: int,
        qdrant_filter: Optional[Filter]
    ) -> list[dict]:
        """Search both vectors and merge results by score."""
        text_vector = self._embed_text(query_text, "text")
        code_vector = self._embed_text(query_text, "code")
        
        results_by_id = {}
        
        for vector_name, vector in [(self.VECTOR_TEXT, text_vector), (self.VECTOR_CODE, code_vector)]:
            try:
                results = self.qdrant.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    using=vector_name,
                    limit=limit * 2,
                    query_filter=qdrant_filter
                ).points
                
                for r in results:
                    if r.id not in results_by_id or r.score > results_by_id[r.id]["score"]:
                        results_by_id[r.id] = {
                            "point": r,
                            "score": r.score,
                            "vector_used": vector_name
                        }
            except Exception as e:
                logger.warning(f"Failed to search {vector_name}: {e}")
        
        sorted_results = sorted(results_by_id.values(), key=lambda x: x["score"], reverse=True)[:limit]
        return self._format_results([r["point"] for r in sorted_results], "both")
    
    def _format_results(self, points: list, vector_used: str) -> list[dict]:
        """Format Qdrant results for output."""
        output = []
        for r in points:
            payload = r.payload or {}
            output.append({
                "text": payload.get("text", ""),
                "doc_name": payload.get("doc_name"),
                "doc_id": payload.get("doc_id"),
                "section_title": payload.get("section_title"),
                "chunk_type": payload.get("chunk_type"),
                "primary_type": payload.get("primary_type"),
                "vector_used": vector_used,
                "score": r.score,
            })
        return output
    
    def list_documents(self) -> list[dict]:
        """
        List all ingested documents with metadata.
        
        Returns unique documents (not chunks).
        """
        if not self.qdrant:
            return []
        
        documents = {}
        
        try:
            result = self.qdrant.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True
            )
            
            for point in result[0]:
                payload = point.payload or {}
                doc_id = payload.get("doc_id")
                
                if doc_id and doc_id not in documents:
                    documents[doc_id] = {
                        "doc_id": doc_id,
                        "doc_name": payload.get("doc_name"),
                        "file_type": payload.get("file_type"),
                        "source": payload.get("source"),
                        "category": payload.get("category"),
                        "tags": payload.get("tags", []),
                        "chunks": 0,
                        "created_at": payload.get("created_at"),
                        "collection": self.collection_name,
                    }
                
                if doc_id:
                    documents[doc_id]["chunks"] += 1
        except Exception as e:
            logger.warning(f"Failed to list documents: {e}")
        
        return list(documents.values())
    
    def delete_document(self, doc_id: Optional[str] = None, doc_name: Optional[str] = None) -> bool:
        """
        Delete document and all its chunks.
        
        Provide either doc_id or doc_name.
        """
        if not self.qdrant:
            return False
        
        if not doc_id and doc_name:
            docs = self.list_documents()
            for doc in docs:
                if doc.get("doc_name") == doc_name:
                    doc_id = doc.get("doc_id")
                    break
        
        if not doc_id:
            return False
        
        try:
            self.qdrant.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                )
            )
            logger.info(f"Deleted document {doc_id} from collection {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False
    
    def save_file(self, source_path: str, source: str) -> str:
        """
        Copy file to persistent storage.
        
        Returns the stored file path.
        """
        dest_dir = os.path.join(DOCUMENTS_DIR, source)
        os.makedirs(dest_dir, exist_ok=True)
        
        filename = os.path.basename(source_path)
        dest_path = os.path.join(dest_dir, filename)
        
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                counter += 1
        
        shutil.copy2(source_path, dest_path)
        return dest_path
    
    def get_collection_info(self) -> dict:
        """Get collection information including vector configurations."""
        if not self.qdrant:
            return {}
        
        try:
            collection = self.qdrant.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": collection.points_count,
                "vectors_config": {
                    name: {"size": v.size, "distance": v.distance.value}
                    for name, v in collection.config.params.vectors.items()
                }
            }
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            return {}


def get_store() -> KnowledgeStore:
    return KnowledgeStore()
