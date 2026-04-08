"""Vault analyzer and optimizer.

Inspects the Qdrant index and the on-disk vault, reports issues, and can
apply a small set of explicit, named optimizations.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor
from src.ingestion.obsidian.parser import OVERSIZED_CHUNK_CHARS, parse_note

logger = logging.getLogger(__name__)


@dataclass
class AnalysisReport:
    note_count: int = 0
    chunk_count: int = 0
    attachment_counts_by_type: dict[str, int] = field(default_factory=dict)
    chunk_size_stats: dict[str, int] = field(default_factory=dict)
    notes_without_headings: list[str] = field(default_factory=list)
    notes_over_50_chunks: list[str] = field(default_factory=list)
    payload_stats: dict[str, Any] = field(default_factory=dict)
    hash_duplicates: list[dict[str, Any]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    missing_indexed_files: list[str] = field(default_factory=list)
    hash_mismatches: list[str] = field(default_factory=list)
    missing_attachments: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_count": self.note_count,
            "chunk_count": self.chunk_count,
            "attachment_counts_by_type": self.attachment_counts_by_type,
            "chunk_size_stats": self.chunk_size_stats,
            "notes_without_headings": self.notes_without_headings,
            "notes_over_50_chunks": self.notes_over_50_chunks,
            "payload_stats": self.payload_stats,
            "hash_duplicates": self.hash_duplicates,
            "orphans": self.orphans,
            "missing_indexed_files": self.missing_indexed_files,
            "hash_mismatches": self.hash_mismatches,
            "missing_attachments": self.missing_attachments,
            "suggestions": self.suggestions,
        }


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def _scroll_all(ingestor: ObsidianVaultIngestor) -> list[dict[str, Any]]:
    if ingestor.qdrant is None:
        return []
    try:
        records, _ = ingestor.qdrant.scroll(
            collection_name=ingestor.collection,
            with_payload=True,
            with_vectors=False,
            limit=100000,
        )
    except TypeError:
        records = ingestor.qdrant.scroll(collection_name=ingestor.collection)
    out = []
    for rec in records or []:
        payload = getattr(rec, "payload", None) or rec.get("payload", {})
        pid = getattr(rec, "id", None) or rec.get("id")
        out.append({"id": pid, "payload": payload})
    return out


def analyze_vault(ingestor: ObsidianVaultIngestor) -> AnalysisReport:
    report = AnalysisReport()

    # -- Index side ----------------------------------------------------
    index_points = _scroll_all(ingestor)
    report.chunk_count = len(index_points)

    sizes: list[int] = []
    per_path: dict[str, list[dict[str, Any]]] = {}
    hash_index: dict[str, list[str]] = {}
    payload_sizes: list[int] = []
    att_counts: dict[str, int] = {}

    for rec in index_points:
        p = rec["payload"]
        content = p.get("content", "") or ""
        sizes.append(len(content))
        payload_sizes.append(len(str(p)))
        vp = p.get("vault_path")
        if vp:
            per_path.setdefault(vp, []).append(rec)
        h = p.get("content_hash")
        if h:
            hash_index.setdefault(h, []).append(f"{vp}#{p.get('chunk_index')}")
        for att in p.get("attachments", []) or []:
            t = att.get("type", "other")
            att_counts[t] = att_counts.get(t, 0) + 1

    report.note_count = len(per_path)
    report.attachment_counts_by_type = att_counts
    if sizes:
        report.chunk_size_stats = {
            "p50": _percentile(sizes, 50),
            "p90": _percentile(sizes, 90),
            "p99": _percentile(sizes, 99),
            "max": max(sizes),
        }
    if payload_sizes:
        report.payload_stats = {
            "avg_bytes": sum(payload_sizes) // len(payload_sizes),
            "max_bytes": max(payload_sizes),
        }

    for h, keys in hash_index.items():
        if len(keys) > 1:
            report.hash_duplicates.append({"hash": h, "locations": keys})

    for vp, recs in per_path.items():
        if len(recs) > 50:
            report.notes_over_50_chunks.append(vp)

    # -- Disk side -----------------------------------------------------
    on_disk: dict[str, Path] = {}
    for root, dirs, files in os.walk(ingestor.vault_path):
        dirs[:] = [
            d
            for d in dirs
            if not (
                d.startswith(".obsidian")
                or d.startswith(".trash")
                or d.startswith(".git")
            )
        ]
        for fname in files:
            if fname.endswith(".md"):
                full = Path(root) / fname
                rel = str(full.relative_to(ingestor.vault_path))
                on_disk[rel] = full

    report.orphans = sorted([vp for vp in per_path if vp not in on_disk])
    report.missing_indexed_files = sorted([vp for vp in on_disk if vp not in per_path])

    # Notes without headings + hash mismatches + missing attachments.
    for rel, full in on_disk.items():
        try:
            parsed = parse_note(full, ingestor.vault_path)
        except Exception as exc:
            logger.warning("Analyze parse failed for %s: %s", rel, exc)
            continue
        if all(c.heading == "_preamble" for c in parsed.chunks):
            report.notes_without_headings.append(rel)
        # Hash mismatches vs index.
        index_hashes = {
            r["payload"].get("chunk_index"): r["payload"].get("content_hash")
            for r in per_path.get(rel, [])
        }
        for c in parsed.chunks:
            if index_hashes.get(c.index) and index_hashes[c.index] != c.content_hash:
                report.hash_mismatches.append(rel)
                break
        for c in parsed.chunks:
            for att in c.attachments:
                att_path = (ingestor.vault_path / att["path"]).resolve()
                if not att_path.exists():
                    report.missing_attachments.append(f"{rel}::{att['path']}")

    # -- Suggestions --------------------------------------------------
    if report.orphans:
        report.suggestions.append(
            f"Run apply_optimization('prune') to remove {len(report.orphans)} orphaned point group(s)."
        )
    if report.chunk_size_stats.get("p99", 0) > OVERSIZED_CHUNK_CHARS:
        report.suggestions.append(
            "p99 chunk size exceeds oversized threshold; consider apply_optimization('rechunk')."
        )
    if report.hash_mismatches:
        report.suggestions.append(
            f"{len(report.hash_mismatches)} file(s) drift from index; consider apply_optimization('resync')."
        )
    if report.missing_indexed_files:
        report.suggestions.append(
            f"{len(report.missing_indexed_files)} note(s) on disk have no index entries; run sync_all()."
        )

    return report


VALID_ACTIONS = ("prune", "rechunk", "resync")


def apply_optimization(ingestor: ObsidianVaultIngestor, action: str) -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"Unknown optimization action {action!r}; expected one of {VALID_ACTIONS}"
        )

    if action == "prune":
        removed = ingestor.prune_orphans()
        return {"action": "prune", "removed_points": removed}

    report = analyze_vault(ingestor)

    if action == "rechunk":
        # v1: re-sync flagged files with full=True so their chunks are
        # re-embedded. The alternate hybrid split is left for a follow-up;
        # this still resolves drift and reduces stale oversized content.
        targets = list(report.notes_over_50_chunks)
        for vp in targets:
            ingestor.sync_file(vp, full=True)
        return {"action": "rechunk", "files_rechunked": targets}

    if action == "resync":
        targets = list(dict.fromkeys(report.hash_mismatches))
        for vp in targets:
            ingestor.sync_file(vp, full=True)
        return {"action": "resync", "files_resynced": targets}

    return {"action": action}
