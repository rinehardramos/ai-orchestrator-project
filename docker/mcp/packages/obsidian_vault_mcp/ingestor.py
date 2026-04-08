"""Standalone Obsidian ingestor — no project imports.

Uses ``qdrant-client`` + the OpenAI-compatible embeddings HTTP endpoint
(LM Studio / Ollama / OpenAI) configured via env vars.
"""
from __future__ import annotations

import datetime
import fnmatch
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from obsidian_vault_mcp.parser import Chunk, ParsedNote, parse_note

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "obsidian_vault_v1"
DEFAULT_QDRANT_URL = "http://host.docker.internal:6333"
DEFAULT_EMBED_URL = "http://host.docker.internal:1234/v1"
DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-code"
DEFAULT_EMBED_DIM = 3584
DEFAULT_IGNORE_GLOBS = (".obsidian/**", ".trash/**", "**/.DS_Store")
_POINT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


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
    """Parses markdown, embeds via an OpenAI-compatible endpoint, upserts to Qdrant."""

    def __init__(
        self,
        vault_path: Optional[str] = None,
        collection: Optional[str] = None,
        qdrant_url: Optional[str] = None,
        embed_url: Optional[str] = None,
        embed_model: Optional[str] = None,
        embed_dim: Optional[int] = None,
        ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
    ) -> None:
        self.vault_path = Path(
            vault_path or os.environ.get("OBSIDIAN_VAULT_PATH") or "/vault"
        ).expanduser().resolve()
        self.collection = (
            collection or os.environ.get("OBSIDIAN_COLLECTION") or DEFAULT_COLLECTION
        )
        self.qdrant_url = (
            qdrant_url or os.environ.get("QDRANT_URL") or DEFAULT_QDRANT_URL
        )
        self.embed_url = (
            embed_url or os.environ.get("EMBEDDING_URL") or DEFAULT_EMBED_URL
        ).rstrip("/")
        self.embed_model = (
            embed_model or os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBED_MODEL
        )
        self.embed_dim = int(
            embed_dim
            or os.environ.get("EMBEDDING_DIM")
            or DEFAULT_EMBED_DIM
        )
        self.ignore_globs = tuple(ignore_globs)

        from qdrant_client import QdrantClient

        self.qdrant = QdrantClient(url=self.qdrant_url)
        self._collection_ready = False
        self._session = requests.Session()

    # ── embedding ───────────────────────────────────────────────────
    def _embed(self, text: str, retries: int = 3) -> list[float]:
        import time

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self._session.post(
                    f"{self.embed_url}/embeddings",
                    headers={"Authorization": "Bearer local"},
                    json={"model": self.embed_model, "input": text},
                    timeout=15,
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
            except Exception as exc:
                last_exc = exc
                time.sleep(0.25 * (2**attempt))
        raise RuntimeError(f"embedding failed after {retries} attempts: {last_exc}")

    # ── collection management ──────────────────────────────────────
    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        from qdrant_client.http.models import Distance, VectorParams

        try:
            self.qdrant.get_collection(self.collection)
        except Exception:
            self.qdrant.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.embed_dim, distance=Distance.COSINE),
            )
        self._collection_ready = True

    # ── existing-point lookup ──────────────────────────────────────
    def _fetch_existing(self, vault_path: str) -> dict[int, tuple[str, str]]:
        self._ensure_collection()
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        flt = Filter(
            must=[FieldCondition(key="vault_path", match=MatchValue(value=vault_path))]
        )
        result: dict[int, tuple[str, str]] = {}
        records, _ = self.qdrant.scroll(
            collection_name=self.collection,
            scroll_filter=flt,
            with_payload=True,
            with_vectors=False,
            limit=1000,
        )
        for rec in records or []:
            payload = rec.payload or {}
            idx = payload.get("chunk_index")
            h = payload.get("content_hash")
            if idx is None or h is None:
                continue
            result[int(idx)] = (str(rec.id), str(h))
        return result

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
            "indexed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def _upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        self._ensure_collection()
        from qdrant_client.http.models import PointStruct

        self.qdrant.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
                for p in points
            ],
        )

    def _delete_points(self, ids: list[str]) -> None:
        if not ids:
            return
        from qdrant_client.http.models import PointIdsList

        self.qdrant.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=ids),
        )

    def _delete_by_vault_path(self, vault_path: str) -> int:
        existing = self._fetch_existing(vault_path)
        ids = [pid for pid, _ in existing.values()]
        self._delete_points(ids)
        return len(ids)

    # ── public API ─────────────────────────────────────────────────
    def sync_file(self, path: str | Path, *, full: bool = False) -> SyncResult:
        result = SyncResult()
        p = Path(path)
        if not p.is_absolute():
            p = self.vault_path / p
        if not p.exists() or not p.is_file():
            deleted = self._delete_by_vault_path(self._relative(p))
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
        desired = {c.index for c in note.chunks}
        points_to_upsert: list[dict[str, Any]] = []

        for chunk in note.chunks:
            have = existing.get(chunk.index)
            if have and have[1] == chunk.content_hash and not full:
                result.unchanged += 1
                continue
            try:
                vec = self._embed(chunk.content or chunk.heading or "_empty_")
            except Exception as exc:
                result.errors.append(
                    f"embed failed for {note.vault_path} chunk {chunk.index}: {exc}"
                )
                continue
            points_to_upsert.append(
                {
                    "id": _point_id(note.vault_path, chunk.index),
                    "vector": vec,
                    "payload": self._build_payload(note, chunk),
                }
            )
            if have:
                result.updated += 1
            else:
                result.added += 1

        self._upsert_points(points_to_upsert)

        stale_ids = [pid for idx, (pid, _) in existing.items() if idx not in desired]
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
            result.merge(self.sync_file(md, full=full))
        result.orphans_pruned += self.prune_orphans()
        return result

    def prune_orphans(self) -> int:
        ids_to_delete: list[str] = []
        records, _ = self.qdrant.scroll(
            collection_name=self.collection,
            with_payload=True,
            with_vectors=False,
            limit=10000,
        )
        for rec in records or []:
            vp = (rec.payload or {}).get("vault_path")
            if not vp:
                continue
            if not (self.vault_path / vp).exists():
                ids_to_delete.append(str(rec.id))
        self._delete_points(ids_to_delete)
        return len(ids_to_delete)

    def search(
        self, query: str, k: int = 8, filter: dict | None = None
    ) -> list[dict[str, Any]]:
        self._ensure_collection()
        vector = self._embed(query)
        hits = self.qdrant.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=k,
            query_filter=filter,
            with_payload=True,
        )
        return [
            {"score": h.score, "payload": h.payload or {}}
            for h in hits or []
        ]

    def get_note(self, vault_path: str) -> list[dict[str, Any]]:
        existing = self._fetch_existing(vault_path)
        if not existing:
            return []
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        flt = Filter(
            must=[FieldCondition(key="vault_path", match=MatchValue(value=vault_path))]
        )
        records, _ = self.qdrant.scroll(
            collection_name=self.collection,
            scroll_filter=flt,
            with_payload=True,
            with_vectors=False,
            limit=1000,
        )
        out = [rec.payload or {} for rec in records or []]
        out.sort(key=lambda p: p.get("chunk_index", 0))
        return out

    # ── helpers ────────────────────────────────────────────────────
    def _relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.vault_path))
        except ValueError:
            return str(path)

    def _walk_vault(self) -> Iterable[Path]:
        for root, dirs, files in os.walk(self.vault_path):
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
