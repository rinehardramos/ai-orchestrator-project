# tests/test_worker_mcp_run_assistant.py
import json, uuid, pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/mcp-servers"))

from packages.worker_mcp.server import (
    AssistantTaskStore,
    _normalize_subject,
)

def test_normalize_subject_strips_dates():
    assert _normalize_subject("EOS Report Gmail Draft - 2026-04-10") == "eos report gmail draft"
    assert _normalize_subject("EOS Report Gmail Draft") == "eos report gmail draft"

def test_normalize_subject_strips_ids():
    assert _normalize_subject("Deploy Task abc123") == "deploy task"

_FAKE_EMBEDDING = [0.0] * 768


def _make_store(search_results):
    """Return an AssistantTaskStore with __init__ bypassed and _embed + _client mocked."""
    store = AssistantTaskStore.__new__(AssistantTaskStore)
    store._collection = "assistant_tasks_test"
    store._embed = MagicMock(return_value=_FAKE_EMBEDDING)
    mock_client = MagicMock()
    mock_client.search.return_value = search_results
    store._client = mock_client
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
    result = store.recall("EOS report", threshold=0.80)
    assert result is not None
    assert result["subject"] == "EOS Report Gmail Draft"
    assert result["score"] >= 0.80

def test_store_recall_returns_none_on_low_confidence():
    store = _make_store([
        MagicMock(score=0.55, id="bbb", payload={"subject": "Something Else"})
    ])
    result = store.recall("EOS report", threshold=0.80)
    assert result is None

def test_store_recall_returns_none_on_empty():
    store = _make_store([])
    result = store.recall("anything", threshold=0.80)
    assert result is None
