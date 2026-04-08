"""Core Obsidian vault ingestor.

Walks a vault, chunks markdown, embeds chunks, and upserts them into a
dedicated Qdrant collection. Uses per-chunk SHA-256 hashes so incremental
syncs only re-embed chunks whose content actually changed.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from src.ingestion.obsidian.attachments import AttachmentRegistry, default_registry
from src.ingestion.obsidian.parser import Chunk, ParsedNote, parse_note

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "obsidian_vault_v1"
DEFAULT_IGNORE_GLOBS = (".obsidian/**", ".trash/**", "**/.DS_Store")
_POINT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_URL


class Embedder(Protocol):
    def embed_text(self, text: str) -> list[float]: ...


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    files_synced: int = 0
    files_skipped: int = 0
    orphans_pruned: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> None:
        self.added += other.added
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.deleted += other.deleted
        self.files_synced += other.files_synced
        self.files_skipped += other.files_skipped
        self.orphans_pruned += other.orphans_pruned
        self.errors.extend(other.errors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deleted": self.deleted,
            "files_synced": self.files_synced,
            "files_skipped": self.files_skipped,
            "orphans_pruned": self.orphans_pruned,
            "errors": self.errors,
        }


def _point_id(vault_path: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{vault_path}::{chunk_index}"))


def _match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


class ObsidianVaultIngestor:
    """Sync an Obsidian vault into a dedicated Qdrant collection."""

    def __init__(
        self,
        vault_path: str | Path,
        collection: str = DEFAULT_COLLECTION,
        embedder: Optional[Embedder] = None,
        qdrant: Any = None,
        registry: Optional[AttachmentRegistry] = None,
        ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
        embed_dim: int | None = None,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.collection = collection
        self.registry = registry or default_registry()
        self.ignore_globs = tuple(ignore_globs)

        if embedder is None:
            from src.shared.memory.knowledge_base import KnowledgeBaseClient

            self._kb = KnowledgeBaseClient()
            self.embedder = self._kb
            if qdrant is None:
                qdrant = self._kb.store.qdrant
            if embed_dim is None:
                embed_dim = getattr(self._kb, "_embed_dim", None)
        else:
            self._kb = None
            self.embedder = embedder

        # Fallback: construct a QdrantClient directly if the embedder's
        # HybridMemoryStore came back with qdrant=None. Uses QDRANT_URL
        # (the canonical env var) or the active environment's qdrant
        # block in settings.yaml.
        if qdrant is None:
            qdrant = self._build_qdrant_fallback()

        self.qdrant = qdrant
        self.embed_dim = embed_dim or getattr(embedder, "_embed_dim", None) or 3584
        self._collection_ready = False

    @staticmethod
    def _build_qdrant_fallback():
        """Build a QdrantClient from ``QDRANT_URL`` or project settings.yaml.

        ``QDRANT_URL`` is the canonical env var across this codebase (see
        tasks/lessons.md). When it is absent, fall back to the qdrant block
        under ``environments.<active_environment>.qdrant`` in
        ``config/settings.yaml``.
        """
        url = os.environ.get("QDRANT_URL")
        if not url:
            try:
                import yaml

                settings_path = (
                    Path(__file__).resolve().parents[3] / "config" / "settings.yaml"
                )
                if settings_path.exists():
                    with settings_path.open("r") as f:
                        data = yaml.safe_load(f) or {}
                    # Top-level qdrant block (legacy).
                    q = data.get("qdrant")
                    if not q:
                        env_name = data.get("active_environment", "primary")
                        q = (
                            data.get("environments", {})
                            .get(env_name, {})
                            .get("qdrant")
                        )
                    if q:
                        url = f"http://{q.get('host', 'localhost')}:{q.get('port', 6333)}"
            except Exception as exc:
                logger.debug("settings.yaml qdrant fallback failed: %s", exc)
        if not url:
            url = "http://localhost:6333"
        try:
            from qdrant_client import QdrantClient

            return QdrantClient(url=url)
        except Exception as exc:
            logger.warning("Failed to build fallback QdrantClient: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------
    def _ensure_collection(self) -> None:
        if self._collection_ready or self.qdrant is None:
            return
        try:
            self.qdrant.get_collection(self.collection)
        except Exception:
            try:
                from qdrant_client.http.models import Distance, VectorParams

                self.qdrant.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(
                        size=self.embed_dim, distance=Distance.COSINE
                    ),
                )
            except Exception as exc:  # pragma: no cover - fake qdrant path
                logger.debug("create_collection via qdrant_client failed: %s", exc)
                if hasattr(self.qdrant, "create_collection"):
                    self.qdrant.create_collection(
                        collection_name=self.collection, size=self.embed_dim
                    )
        self._collection_ready = True

    # ------------------------------------------------------------------
    # Existing-point lookup
    # ------------------------------------------------------------------
    def _fetch_existing(self, vault_path: str) -> dict[int, tuple[str, str]]:
        """Return {chunk_index: (point_id, content_hash)} for a given file."""
        self._ensure_collection()
        if self.qdrant is None:
            return {}
        try:
            from qdrant_client.http.models import FieldCondition, Filter, MatchValue

            flt = Filter(
                must=[FieldCondition(key="vault_path", match=MatchValue(value=vault_path))]
            )
        except Exception:
            flt = {"must": [{"key": "vault_path", "match": {"value": vault_path}}]}

        result: dict[int, tuple[str, str]] = {}
        try:
            records, _ = self.qdrant.scroll(
                collection_name=self.collection,
                scroll_filter=flt,
                with_payload=True,
                with_vectors=False,
                limit=1000,
            )
        except TypeError:
            # FakeQdrant signature.
            records = self.qdrant.scroll(
                collection_name=self.collection, scroll_filter=flt
            )
        for rec in records or []:
            payload = getattr(rec, "payload", None) or rec.get("payload", {})
            pid = getattr(rec, "id", None) or rec.get("id")
            idx = payload.get("chunk_index")
            h = payload.get("content_hash")
            if idx is None or h is None or pid is None:
                continue
            result[int(idx)] = (str(pid), str(h))
        return result

    # ------------------------------------------------------------------
    # Upsert / delete
    # ------------------------------------------------------------------
    def _build_payload(self, note: ParsedNote, chunk: Chunk) -> dict[str, Any]:
        return {
            "vault_path": note.vault_path,
            "absolute_path": note.absolute_path,
            "chunk_index": chunk.index,
            "heading": chunk.heading,
            "heading_path": chunk.heading_path,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "frontmatter": note.frontmatter,
            "tags": chunk.tags,
            "links": chunk.links,
            "attachments": chunk.attachments,
            "source_type": "note",
            "file_mtime": note.file_mtime,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not points or self.qdrant is None:
            return
        self._ensure_collection()
        try:
            from qdrant_client.http.models import PointStruct

            structs = [
                PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
                for p in points
            ]
            self.qdrant.upsert(collection_name=self.collection, points=structs)
        except Exception:
            # Fallback: fake client accepts plain dicts.
            self.qdrant.upsert(collection_name=self.collection, points=points)

    def _delete_points(self, point_ids: list[str]) -> None:
        if not point_ids or self.qdrant is None:
            return
        try:
            from qdrant_client.http.models import PointIdsList

            self.qdrant.delete(
                collection_name=self.collection,
                points_selector=PointIdsList(points=point_ids),
            )
        except Exception:
            self.qdrant.delete(
                collection_name=self.collection, points_selector=point_ids
            )

    def _delete_by_vault_path(self, vault_path: str) -> int:
        if self.qdrant is None:
            return 0
        existing = self._fetch_existing(vault_path)
        ids = [pid for pid, _ in existing.values()]
        self._delete_points(ids)
        return len(ids)

    # ------------------------------------------------------------------
    # Embedding helper (with minimal retry)
    # ------------------------------------------------------------------
    def _embed(self, text: str, retries: int = 3) -> list[float]:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                vec = self.embedder.embed_text(text)
                if vec is None:
                    raise RuntimeError("embedder returned None")
                return vec
            except Exception as exc:
                last_exc = exc
                time.sleep(0.25 * (2**attempt))
        raise RuntimeError(f"embedding failed after {retries} attempts: {last_exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def sync_file(self, path: str | Path, *, full: bool = False) -> SyncResult:
        """Sync a single note. ``full=True`` re-embeds every chunk."""
        result = SyncResult()
        p = Path(path)
        if not p.is_absolute():
            p = self.vault_path / p
        if not p.exists() or not p.is_file():
            # File no longer exists → treat as delete.
            vault_rel = self._relative(p)
            deleted = self._delete_by_vault_path(vault_rel)
            result.deleted += deleted
            result.files_synced += 1 if deleted else 0
            return result

        try:
            note = parse_note(p, self.vault_path)
        except Exception as exc:
            result.errors.append(f"parse failed for {p}: {exc}")
            result.files_skipped += 1
            return result

        existing = {} if full else self._fetch_existing(note.vault_path)
        desired_indices = {c.index for c in note.chunks}

        points_to_upsert: list[dict[str, Any]] = []
        for chunk in note.chunks:
            existing_entry = existing.get(chunk.index)
            if existing_entry and existing_entry[1] == chunk.content_hash and not full:
                result.unchanged += 1
                continue
            try:
                vector = self._embed(chunk.content or chunk.heading or "_empty_")
            except Exception as exc:
                result.errors.append(
                    f"embed failed for {note.vault_path} chunk {chunk.index}: {exc}"
                )
                continue
            points_to_upsert.append(
                {
                    "id": _point_id(note.vault_path, chunk.index),
                    "vector": vector,
                    "payload": self._build_payload(note, chunk),
                }
            )
            if existing_entry:
                result.updated += 1
            else:
                result.added += 1

        self._upsert_points(points_to_upsert)

        # Delete chunks that existed before but aren't present anymore.
        stale_ids = [
            pid
            for idx, (pid, _) in existing.items()
            if idx not in desired_indices
        ]
        if stale_ids:
            self._delete_points(stale_ids)
            result.deleted += len(stale_ids)

        result.files_synced += 1
        return result

    def delete_file(self, vault_path: str) -> SyncResult:
        result = SyncResult()
        result.deleted = self._delete_by_vault_path(vault_path)
        return result

    def sync_all(self, *, full: bool = False) -> SyncResult:
        result = SyncResult()
        for md in self._walk_vault():
            file_result = self.sync_file(md, full=full)
            result.merge(file_result)
        result.orphans_pruned += self.prune_orphans()
        return result

    def prune_orphans(self) -> int:
        """Delete points whose source file is no longer present on disk."""
        if self.qdrant is None:
            return 0
        seen_paths: set[str] = set()
        ids_to_delete: list[str] = []
        try:
            records, _ = self.qdrant.scroll(
                collection_name=self.collection,
                with_payload=True,
                with_vectors=False,
                limit=10000,
            )
        except TypeError:
            records = self.qdrant.scroll(collection_name=self.collection)
        for rec in records or []:
            payload = getattr(rec, "payload", None) or rec.get("payload", {})
            pid = getattr(rec, "id", None) or rec.get("id")
            vp = payload.get("vault_path")
            if not vp or pid is None:
                continue
            seen_paths.add(vp)
            abs_path = self.vault_path / vp
            if not abs_path.exists():
                ids_to_delete.append(str(pid))
        self._delete_points(ids_to_delete)
        return len(ids_to_delete)

    def search(
        self, query: str, k: int = 8, filter: dict | None = None
    ) -> list[dict[str, Any]]:
        if self.qdrant is None:
            return []
        self._ensure_collection()
        vector = self._embed(query)
        try:
            hits = self.qdrant.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=k,
                query_filter=filter,
                with_payload=True,
            )
        except TypeError:
            hits = self.qdrant.search(
                collection_name=self.collection, query_vector=vector, limit=k
            )
        out: list[dict[str, Any]] = []
        for h in hits or []:
            payload = getattr(h, "payload", None) or h.get("payload", {})
            score = getattr(h, "score", None) or h.get("score")
            out.append({"score": score, "payload": payload})
        return out

    def get_note(self, vault_path: str) -> list[dict[str, Any]]:
        existing = self._fetch_existing(vault_path)
        # Fetch payloads by re-scrolling (simpler than keeping them around).
        if self.qdrant is None or not existing:
            return []
        try:
            from qdrant_client.http.models import FieldCondition, Filter, MatchValue

            flt = Filter(
                must=[FieldCondition(key="vault_path", match=MatchValue(value=vault_path))]
            )
        except Exception:
            flt = {"must": [{"key": "vault_path", "match": {"value": vault_path}}]}
        try:
            records, _ = self.qdrant.scroll(
                collection_name=self.collection,
                scroll_filter=flt,
                with_payload=True,
                with_vectors=False,
                limit=1000,
            )
        except TypeError:
            records = self.qdrant.scroll(
                collection_name=self.collection, scroll_filter=flt
            )
        out = []
        for rec in records or []:
            payload = getattr(rec, "payload", None) or rec.get("payload", {})
            out.append(payload)
        out.sort(key=lambda p: p.get("chunk_index", 0))
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.vault_path))
        except ValueError:
            return str(path)

    def _walk_vault(self) -> Iterable[Path]:
        for root, dirs, files in os.walk(self.vault_path):
            # Prune ignored directories in place.
            pruned_dirs = []
            for d in dirs:
                rel_dir = os.path.relpath(os.path.join(root, d), self.vault_path)
                if _match_any(rel_dir + "/", self.ignore_globs):
                    continue
                pruned_dirs.append(d)
            dirs[:] = pruned_dirs

            for fname in files:
                if not fname.endswith(".md"):
                    continue
                full_path = Path(root) / fname
                rel = os.path.relpath(full_path, self.vault_path)
                if _match_any(rel, self.ignore_globs):
                    continue
                yield full_path
