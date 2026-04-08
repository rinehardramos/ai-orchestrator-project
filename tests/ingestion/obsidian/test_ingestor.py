from __future__ import annotations

from pathlib import Path


def _all_points(fake_qdrant, collection="obsidian_test"):
    return list(fake_qdrant.collections.get(collection, {}).values())


def test_full_sync_indexes_every_note(ingestor, fake_qdrant):
    result = ingestor.sync_all()
    assert result.files_synced >= 4  # README + 4 fixture notes
    assert result.added > 0
    pts = _all_points(fake_qdrant)
    assert pts, "expected points to be written"
    vault_paths = {p.payload["vault_path"] for p in pts}
    assert "No Headings.md" in vault_paths


def test_incremental_no_change_reembeds_nothing(ingestor, fake_embedder, fake_qdrant):
    ingestor.sync_all()
    before = len(fake_embedder.calls)
    result = ingestor.sync_all()
    after = len(fake_embedder.calls)
    assert after == before, "incremental sync should not re-embed unchanged chunks"
    assert result.added == 0
    assert result.updated == 0
    assert result.unchanged > 0


def test_incremental_only_affected_chunk_reembeds(ingestor, fake_embedder, tmp_vault: Path):
    ingestor.sync_all()
    before = len(fake_embedder.calls)
    target = tmp_vault / "Daily" / "2026-04-08.md"
    content = target.read_text()
    new_content = content.replace("Reviewed the orchestrator queue", "Reviewed the NEW queue")
    target.write_text(new_content)

    result = ingestor.sync_file("Daily/2026-04-08.md")
    after = len(fake_embedder.calls)
    # Only one chunk changed.
    assert result.updated == 1
    assert result.added == 0
    assert after - before == 1


def test_section_deleted_removes_chunk(ingestor, fake_qdrant, tmp_vault: Path):
    ingestor.sync_all()
    target = tmp_vault / "Research" / "Vectors.md"
    text = target.read_text()
    # Drop the "## Distance metrics" section.
    new_text = text.split("## Distance metrics")[0]
    target.write_text(new_text)

    result = ingestor.sync_file("Research/Vectors.md")
    assert result.deleted >= 1
    pts = [
        p
        for p in _all_points(fake_qdrant)
        if p.payload.get("vault_path") == "Research/Vectors.md"
    ]
    assert not any(p.payload.get("heading") == "Distance metrics" for p in pts)


def test_whole_file_deleted(ingestor, fake_qdrant, tmp_vault: Path):
    ingestor.sync_all()
    (tmp_vault / "No Headings.md").unlink()
    result = ingestor.sync_file("No Headings.md")
    assert result.deleted >= 1
    pts = [
        p
        for p in _all_points(fake_qdrant)
        if p.payload.get("vault_path") == "No Headings.md"
    ]
    assert not pts


def test_rename_is_delete_plus_add(ingestor, fake_qdrant, tmp_vault: Path):
    ingestor.sync_all()
    old = tmp_vault / "No Headings.md"
    new = tmp_vault / "Renamed.md"
    old.rename(new)
    ingestor.delete_file("No Headings.md")
    ingestor.sync_file("Renamed.md")
    paths = {p.payload["vault_path"] for p in _all_points(fake_qdrant)}
    assert "Renamed.md" in paths
    assert "No Headings.md" not in paths


def test_prune_orphans(ingestor, fake_qdrant, tmp_vault: Path):
    ingestor.sync_all()
    (tmp_vault / "No Headings.md").unlink()
    removed = ingestor.prune_orphans()
    assert removed >= 1
    paths = {p.payload["vault_path"] for p in _all_points(fake_qdrant)}
    assert "No Headings.md" not in paths


def test_full_flag_reembeds_everything(ingestor, fake_embedder):
    ingestor.sync_all()
    before = len(fake_embedder.calls)
    ingestor.sync_all(full=True)
    after = len(fake_embedder.calls)
    assert after > before


def test_get_note_returns_chunks_in_order(ingestor):
    ingestor.sync_all()
    chunks = ingestor.get_note("Research/Vectors.md")
    indices = [c["chunk_index"] for c in chunks]
    assert indices == sorted(indices)
    assert len(indices) >= 2
