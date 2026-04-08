"""Shared fixtures for Obsidian ingestion tests.

We use an in-memory fake Qdrant so the ingestor can be exercised without
a running Qdrant instance (tests run on CI/workers, not the Genesis
node). The fake implements exactly the narrow slice of the Qdrant API
used by :class:`ObsidianVaultIngestor`.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake embedder
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic 16-dim embedder derived from SHA-256 of the input."""

    _embed_dim = 16

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Take first 16 bytes, normalize into [-1, 1].
        return [((b / 127.5) - 1.0) for b in h[:16]]


# ---------------------------------------------------------------------------
# Fake Qdrant
# ---------------------------------------------------------------------------
@dataclass
class _FakePoint:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


class FakeQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, _FakePoint]] = {}
        self.delete_calls: list[tuple[str, list[str]]] = []

    # -- collection management -------------------------------------------
    def get_collection(self, collection_name: str):
        if collection_name not in self.collections:
            raise Exception("collection missing")
        return {"name": collection_name}

    def create_collection(self, collection_name: str, **kwargs):  # noqa: ARG002
        self.collections.setdefault(collection_name, {})

    # -- upsert / delete -------------------------------------------------
    def _ensure(self, name: str) -> dict[str, _FakePoint]:
        return self.collections.setdefault(name, {})

    def upsert(self, collection_name: str, points):
        bucket = self._ensure(collection_name)
        for p in points:
            if hasattr(p, "id"):
                pid = p.id
                vec = p.vector
                payload = p.payload
            else:
                pid = p["id"]
                vec = p["vector"]
                payload = p["payload"]
            bucket[str(pid)] = _FakePoint(id=str(pid), vector=list(vec), payload=dict(payload))

    def delete(self, collection_name: str, points_selector):
        bucket = self._ensure(collection_name)
        if hasattr(points_selector, "points"):
            ids = [str(x) for x in points_selector.points]
        elif isinstance(points_selector, list):
            ids = [str(x) for x in points_selector]
        else:
            ids = []
        for pid in ids:
            bucket.pop(pid, None)
        self.delete_calls.append((collection_name, ids))

    # -- scroll / search -------------------------------------------------
    def _match(self, payload: dict[str, Any], flt) -> bool:
        if flt is None:
            return True
        must = getattr(flt, "must", None)
        if must is None and isinstance(flt, dict):
            must = flt.get("must")
        for cond in must or []:
            key = getattr(cond, "key", None) or cond.get("key")
            match_obj = getattr(cond, "match", None) or cond.get("match")
            value = getattr(match_obj, "value", None) if hasattr(match_obj, "value") else (
                match_obj.get("value") if isinstance(match_obj, dict) else None
            )
            if payload.get(key) != value:
                return False
        return True

    def scroll(
        self,
        collection_name: str,
        scroll_filter=None,
        with_payload: bool = True,  # noqa: ARG002
        with_vectors: bool = False,  # noqa: ARG002
        limit: int = 10000,  # noqa: ARG002
    ):
        bucket = self._ensure(collection_name)
        results = [p for p in bucket.values() if self._match(p.payload, scroll_filter)]
        return results, None

    def search(
        self,
        collection_name: str,
        query_vector,  # noqa: ARG002
        limit: int = 8,
        query_filter=None,
        with_payload: bool = True,  # noqa: ARG002
    ):
        bucket = self._ensure(collection_name)
        results = [p for p in bucket.values() if self._match(p.payload, query_filter)]
        # Not actually scoring — tests only inspect payloads.
        out = []
        for p in results[:limit]:
            out.append(type("Hit", (), {"id": p.id, "score": 1.0, "payload": p.payload})())
        return out


# ---------------------------------------------------------------------------
# Vault + ingestor fixtures
# ---------------------------------------------------------------------------
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE_DIR, dest)
    return dest


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_qdrant() -> FakeQdrant:
    return FakeQdrant()


@pytest.fixture
def ingestor(tmp_vault: Path, fake_embedder, fake_qdrant):
    from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor

    return ObsidianVaultIngestor(
        vault_path=tmp_vault,
        collection="obsidian_test",
        embedder=fake_embedder,
        qdrant=fake_qdrant,
        embed_dim=FakeEmbedder._embed_dim,
    )
