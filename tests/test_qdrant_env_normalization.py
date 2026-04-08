"""Enforcement test for QDRANT_URL normalization.

``QDRANT_URL`` is the canonical Qdrant environment variable across this
codebase. ``QDRANT_HOST`` has been retired. This test asserts no tracked
file in the main tree reintroduces ``QDRANT_HOST``. See tasks/lessons.md
for the rationale.

The enforcement is file-level rather than runtime so it catches drift in
code, docs, shell scripts, compose files, and env templates in one pass.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

FORBIDDEN = re.compile(r"\bQDRANT_HOST\b")

# Files that are explicitly allowed to mention the retired name because
# they exist to prevent its return (this test + the lessons doc).
ALLOWLIST = {
    "tests/test_qdrant_env_normalization.py",
    "tasks/lessons.md",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tracked_files() -> list[str]:
    root = _repo_root()
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=root, text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        pytest.skip("git not available; cannot enumerate tracked files")
    return [
        p.strip()
        for p in out.splitlines()
        if p.strip() and not p.startswith(".claude/worktrees/")
    ]


def test_qdrant_host_is_not_used_anywhere():
    root = _repo_root()
    offenders: list[str] = []
    for rel in _tracked_files():
        if rel in ALLOWLIST:
            continue
        p = root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if FORBIDDEN.search(text):
            offenders.append(rel)
    assert not offenders, (
        "QDRANT_HOST has been retired in favor of QDRANT_URL. "
        "See tasks/lessons.md. Offending files:\n  " + "\n  ".join(offenders)
    )
