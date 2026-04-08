from __future__ import annotations

import pytest

from src.ingestion.obsidian.mcp_server import ObsidianMcpHandlers


@pytest.fixture
def handlers(ingestor):
    ingestor.sync_all()
    return ObsidianMcpHandlers(ingestor)


def test_search_requires_non_empty_query(handlers):
    with pytest.raises(ValueError):
        handlers.search_vault("")


def test_search_returns_hits(handlers):
    hits = handlers.search_vault("embeddings", k=3)
    assert isinstance(hits, list)


def test_get_note_returns_chunks(handlers):
    chunks = handlers.get_note("Research/Vectors.md")
    assert len(chunks) >= 1


def test_sync_vault_rejects_bad_mode(handlers):
    with pytest.raises(ValueError):
        handlers.sync_vault(mode="turbo")


def test_sync_vault_single_path(handlers):
    result = handlers.sync_vault(mode="incremental", path="Research/Vectors.md")
    assert result["files_synced"] >= 1


def test_analyze_returns_dict(handlers):
    report = handlers.analyze_vault()
    assert "chunk_count" in report
    assert "orphans" in report


def test_apply_rejects_unknown_action(handlers):
    with pytest.raises(ValueError):
        handlers.apply_vault_optimization("delete_everything")


def test_apply_prune_allowed(handlers):
    result = handlers.apply_vault_optimization("prune")
    assert result["action"] == "prune"
