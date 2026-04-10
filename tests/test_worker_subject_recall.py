# tests/test_worker_subject_recall.py
"""
Unit tests for resolve_subject, preflight_tools, LowConfidenceError,
and ToolUnavailableError added to src/execution/worker/worker.py.

Heavy third-party dependencies (temporalio, langgraph, boto3, etc.) and
src-level modules that require external services are stubbed via sys.modules
before any worker import so these tests run locally without the Docker
worker environment.
"""
import pytest
import sys
import os
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Insert the worktree root onto sys.path so `src.*` resolves correctly.
# ---------------------------------------------------------------------------
_WORKTREE = "/Users/rinehardramos/.config/superpowers/worktrees/ai-orchestrator-project/feature/run-assistant-mcp"
if _WORKTREE not in sys.path:
    sys.path.insert(0, _WORKTREE)

# ---------------------------------------------------------------------------
# Stub every third-party module unavailable in the local environment.
# Must happen BEFORE any `from src.execution.worker.worker import …`
# ---------------------------------------------------------------------------

_THIRD_PARTY_STUBS = [
    # Temporal
    "temporalio",
    "temporalio.activity",
    "temporalio.workflow",
    "temporalio.common",
    "temporalio.client",
    "temporalio.worker",
    # Langgraph
    "langgraph",
    "langgraph.graph",
    # opik
    "opik",
    # qdrant_client (only called inside _get_assistant_task_store; mocked in tests)
    "qdrant_client",
    # boto3 / botocore (used in shared memory modules)
    "boto3",
    "botocore",
    "botocore.exceptions",
    # asyncpg / redis (budget tracking)
    "asyncpg",
    "redis",
    "redis.asyncio",
    # sentence_transformers (embeddings — not called in tests)
    "sentence_transformers",
    # openai (used in model_router)
    "openai",
    "openai.types",
    "openai.types.chat",
]

for _name in _THIRD_PARTY_STUBS:
    sys.modules.setdefault(_name, MagicMock())

# ---------------------------------------------------------------------------
# Stub src-level modules that require external services (DB, Redis, Qdrant).
# We stub them BEFORE the real modules are imported so Python never tries to
# execute their module-level code.
# ---------------------------------------------------------------------------

# src.config / src.config_db
_config_stub = MagicMock()
_config_stub.load_settings.return_value = {
    "temporal": {},
    "qdrant": {"host": "localhost", "port": 6333},
    "redis": {"host": "localhost", "port": 6379},
}
sys.modules.setdefault("src.config", _config_stub)

_config_db_stub = MagicMock()
_loader_stub = MagicMock()
_loader_stub.load_namespace.return_value = {}
_loader_stub.load_all_namespaces.return_value = {}
_config_db_stub.get_loader.return_value = _loader_stub
sys.modules.setdefault("src.config_db", _config_db_stub)

# src.shared.memory.*  — imported at the top of worker.py
_hybrid_mod = MagicMock()
_hybrid_mod.HybridMemoryStore = MagicMock()
_hybrid_mod.MemoryEntry = MagicMock()
sys.modules.setdefault("src.shared", MagicMock())
sys.modules.setdefault("src.shared.memory", MagicMock())
sys.modules.setdefault("src.shared.memory.hybrid_store", _hybrid_mod)
sys.modules.setdefault("src.shared.memory.knowledge_base", MagicMock())
sys.modules.setdefault("src.shared.memory.decay_workflow", MagicMock())

# src.shared.budget.tracker
_budget_mod = MagicMock()
_budget_mod.budget_tracker = None
sys.modules.setdefault("src.shared.budget", MagicMock())
sys.modules.setdefault("src.shared.budget.tracker", _budget_mod)

# ---------------------------------------------------------------------------
# Fine-tune Temporal stubs — the decorators must be callable.
# ---------------------------------------------------------------------------
import temporalio.activity as _ta  # type: ignore
_ta.defn = lambda fn=None, **kw: (fn if fn else lambda f: f)
_ta.run = MagicMock()

import temporalio.workflow as _tw  # type: ignore
_tw.defn = lambda fn=None, **kw: (fn if fn else lambda f: f)
_tw.run = MagicMock()

import temporalio.common as _tc  # type: ignore
_tc.RetryPolicy = MagicMock()

import temporalio.client as _tcli  # type: ignore
_tcli.Client = MagicMock()

import temporalio.worker as _tw2  # type: ignore
_tw2.Worker = MagicMock()
_tw2.UnsandboxedWorkflowRunner = MagicMock()

# Langgraph constants used at module level in worker.py
import langgraph.graph as _lg_graph  # type: ignore
_lg_graph.START = "START"
_lg_graph.END = "END"
_lg_graph.StateGraph = MagicMock()

# ---------------------------------------------------------------------------
# Actual tests
# ---------------------------------------------------------------------------

def test_resolve_subject_raises_on_low_confidence():
    from src.execution.worker.worker import resolve_subject, LowConfidenceError
    mock_store = MagicMock()
    mock_store.recall.return_value = None  # below threshold
    with pytest.raises(LowConfidenceError):
        import asyncio
        asyncio.run(resolve_subject("unknown task xyz", mock_store))


def test_resolve_subject_returns_filled_prompt():
    from src.execution.worker.worker import resolve_subject
    from datetime import date
    mock_store = MagicMock()
    mock_store.recall.return_value = {
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaa",
        "score": 0.92,
        "steps": [
            {"n": 1, "action": "qdrant_recall", "params": {"note": "EOS Report"}},
            {"n": 2, "action": "gmail_draft",    "params": {"subject": "EOS Report - {today}"}},
        ],
        "required_tools": ["qdrant_recall", "gmail_draft"],
    }
    import asyncio
    result = asyncio.run(resolve_subject("EOS report", mock_store))
    assert "Subject: EOS Report Gmail Draft" in result["task_description"]
    assert str(date.today()) in result["task_description"]
    assert result["required_tools"] == ["qdrant_recall", "gmail_draft"]
    assert result["qdrant_key"] == "aaa"


def test_preflight_raises_on_missing_tool():
    from src.execution.worker.worker import preflight_tools, ToolUnavailableError
    with pytest.raises(ToolUnavailableError) as exc_info:
        preflight_tools(["shell_exec", "nonexistent_tool_xyz"])
    assert "nonexistent_tool_xyz" in str(exc_info.value)


def test_preflight_passes_for_known_tools():
    from src.execution.worker.worker import preflight_tools
    # shell_exec should always be registered
    preflight_tools(["shell_exec"])  # should not raise


import asyncio as _asyncio
from unittest.mock import AsyncMock, patch


def test_run_agent_pipeline_routes_subject_task():
    """When task_description starts with 'Subject: ', resolve_subject is called."""
    from src.execution.worker.worker import run_agent_pipeline

    subject_payload = {
        "description": "Subject: EOS Report Gmail Draft",
        "specialization": "assistant",
        "max_tool_calls": 5,
        "max_cost_usd": 0.10,
    }

    mock_store = MagicMock()
    mock_store.recall.return_value = {
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaa",
        "score": 0.92,
        "steps": [{"n": 1, "action": "shell_exec", "params": {"command": "echo hello"}}],
        "required_tools": ["shell_exec"],
    }

    async def _run():
        with patch("src.execution.worker.worker._get_assistant_task_store", return_value=mock_store), \
             patch("src.execution.worker.worker._run_react_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = {"status": "completed", "summary": "done", "total_cost_usd": 0.0, "tool_call_count": 1, "artifact_files": []}
            result = await run_agent_pipeline(subject_payload, "gemma-4b")
        mock_store.recall.assert_called_once()
        assert result["status"] == "completed"

    _asyncio.run(_run())
