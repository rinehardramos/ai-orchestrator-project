# tests/test_worker_mcp_run_assistant.py
import json, uuid, pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/mcp-servers"))

try:
    from packages.worker_mcp.server import (
        AssistantTaskStore,
        _normalize_subject,
    )
except ModuleNotFoundError:
    pytest.skip("worker_mcp package not installed (local-only)", allow_module_level=True)

def test_normalize_subject_strips_dates():
    assert _normalize_subject("EOS Report Gmail Draft - 2026-04-10") == "eos report gmail draft"
    assert _normalize_subject("EOS Report Gmail Draft") == "eos report gmail draft"

def test_normalize_subject_strips_ids():
    assert _normalize_subject("Deploy Task abc123") == "deploy task"

_FAKE_EMBEDDING = [0.0] * 768


def _make_store(search_results):
    """Return an AssistantTaskStore with __init__ bypassed, _embed + _search mocked."""
    store = AssistantTaskStore.__new__(AssistantTaskStore)
    store._collection = "assistant_tasks_test"
    store._embed = MagicMock(return_value=_FAKE_EMBEDDING)
    # Mock _search directly (avoids coupling to qdrant_client API version)
    store._search = MagicMock(return_value=search_results)
    return store


def test_store_recall_returns_payload_on_match():
    """recall returns payload+score dict when score >= threshold."""
    store = _make_store([
        MagicMock(score=0.95, id="aaa", payload={
            "subject": "EOS Report Gmail Draft",
            "subject_normalized": "eos report gmail draft",
            "steps": [{"n": 1, "action": "qdrant_recall", "params": {"note": "EOS Report"}}],
            "required_tools": ["qdrant_recall"],
            "last_outcome": "",
            "step_outcomes": {},
            "version": 1,
        })
    ])
    result = store.recall("EOS report", threshold=0.50)
    assert result is not None
    assert result["subject"] == "EOS Report Gmail Draft"
    assert result["score"] >= 0.50

def test_store_recall_returns_none_on_low_confidence():
    store = _make_store([
        MagicMock(score=0.30, id="bbb", payload={"subject": "Something Else"})
    ])
    result = store.recall("EOS report", threshold=0.50)
    assert result is None

def test_store_recall_returns_none_on_empty():
    store = _make_store([])
    result = store.recall("anything", threshold=0.50)
    assert result is None


# ── WorkerApiClient.run_assistant tests ─────────────────────────────────────

from packages.worker_mcp.server import WorkerApiClient

def _make_client():
    """Create WorkerApiClient with fake base_url and key."""
    return WorkerApiClient(base_url="http://fake", api_key="k")

def test_gap_fill_returned_when_no_hint_match():
    client = _make_client()
    store = MagicMock()
    store.recall.return_value = None
    store.recall_candidates.return_value = []
    result = client.run_assistant(hint="unknown task xyz", details=None, _store=store)
    assert result["clarify"] is True
    assert isinstance(result["questions"], list)
    assert len(result["questions"]) >= 3

def test_recall_dispatches_when_subject_found():
    client = _make_client()
    store = MagicMock()
    store.recall.return_value = {
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaa",
        "score": 0.91,
        "steps": [{"n": 1, "action": "gmail_draft", "params": {}}],
        "required_tools": ["gmail_draft"],
    }
    client._request = MagicMock(return_value={"task_id": "t-123", "specialization": "assistant", "status": "submitted"})
    result = client.run_assistant(hint="EOS report", details=None, _store=store)
    assert result["dispatched"] is True
    assert result["task_id"] == "t-123"
    assert result["subject"] == "EOS Report Gmail Draft"

def test_disambiguation_when_multiple_close_matches():
    client = _make_client()
    store = MagicMock()
    store.recall.return_value = None
    store.recall_candidates.return_value = [
        {"subject": "EOS Report Gmail Draft", "score": 0.88, "qdrant_key": "a"},
        {"subject": "EOS Summary Slack Post", "score": 0.85, "qdrant_key": "b"},
    ]
    result = client.run_assistant(hint="EOS", details=None, _store=store)
    assert result.get("confirm_subject") is True
    assert len(result["candidates"]) == 2

def test_seed_stores_and_dispatches():
    client = _make_client()
    store = MagicMock()
    store.recall.return_value = None
    store.recall_candidates.return_value = []
    store.seed.return_value = "new-qdrant-key"
    client._request = MagicMock(side_effect=[
        None,  # POST /tasks/subjects (register in control plane)
        {"task_id": "t-456", "specialization": "assistant", "status": "submitted"},
    ])
    details = "1. Find EOS Report in Qdrant\n2. Draft Gmail to recipient\n3. Send as draft"
    result = client.run_assistant(hint="EOS report", details=details, _store=store)
    assert result["seeded"] is True
    assert result["task_id"] == "t-456"
