from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.obsidian.analyzer import (
    VALID_ACTIONS,
    analyze_vault,
    apply_optimization,
)


def test_analyze_reports_counts(ingestor):
    ingestor.sync_all()
    report = analyze_vault(ingestor)
    assert report.note_count >= 4
    assert report.chunk_count > 0
    assert "p50" in report.chunk_size_stats


def test_analyze_detects_orphans(ingestor, tmp_vault: Path):
    ingestor.sync_all()
    (tmp_vault / "No Headings.md").unlink()
    report = analyze_vault(ingestor)
    assert "No Headings.md" in report.orphans
    assert any("prune" in s for s in report.suggestions)


def test_analyze_detects_missing_indexed_files(ingestor, tmp_vault: Path):
    ingestor.sync_all()
    (tmp_vault / "Fresh.md").write_text("# Fresh\n\nnew content\n")
    report = analyze_vault(ingestor)
    assert "Fresh.md" in report.missing_indexed_files


def test_analyze_detects_hash_mismatch(ingestor, tmp_vault: Path):
    ingestor.sync_all()
    target = tmp_vault / "Research" / "Vectors.md"
    target.write_text(target.read_text().replace("Cosine works well", "Cosine is fine"))
    report = analyze_vault(ingestor)
    assert "Research/Vectors.md" in report.hash_mismatches


def test_analyze_detects_notes_without_headings(ingestor):
    ingestor.sync_all()
    report = analyze_vault(ingestor)
    assert "No Headings.md" in report.notes_without_headings


def test_apply_unknown_action_raises(ingestor):
    with pytest.raises(ValueError):
        apply_optimization(ingestor, "nuke")


def test_apply_prune_removes_orphans(ingestor, tmp_vault: Path):
    ingestor.sync_all()
    (tmp_vault / "No Headings.md").unlink()
    result = apply_optimization(ingestor, "prune")
    assert result["action"] == "prune"
    assert result["removed_points"] >= 1


def test_valid_actions_contains_expected():
    assert set(VALID_ACTIONS) == {"prune", "rechunk", "resync"}
