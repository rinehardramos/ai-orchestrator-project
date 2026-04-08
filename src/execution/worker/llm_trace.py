"""Per-task JSONL trace of LLM prompts, responses, and tool calls.

The worker calls :func:`set_task` when it begins an activity and then
:func:`emit` from inside the ReAct loop. Each call appends one JSON line
to ``${LLM_TRACE_DIR:-/tmp/llm-traces}/{task_id}.jsonl``.

The directory is host-mounted at ``/tmp/orchestrator-llm-traces`` so the
Genesis-side CLI (``src.genesis.llm_logs``) can tail it directly. ``/tmp``
is cleaned by the OS on reboot, so traces are ephemeral by design.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("llm_trace")

_TRACE_DIR = Path(os.environ.get("LLM_TRACE_DIR", "/tmp/llm-traces"))  # nosec B108 — ephemeral by design (host /tmp wiped on reboot)
_MAX_FIELD_CHARS = 20_000  # truncate runaway prompts so disk stays bounded

_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_trace_task_id", default=None)


def set_task(task_id: str | None) -> None:
    """Bind the active task id for subsequent :func:`emit` calls."""
    _task_id.set(task_id)
    if task_id:
        try:
            _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("llm_trace: cannot create %s: %s", _TRACE_DIR, exc)


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
        return value[:_MAX_FIELD_CHARS] + f"…(+{len(value) - _MAX_FIELD_CHARS} chars)"
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    return value


def emit(event: str, **fields: Any) -> None:
    """Append one trace event for the active task. No-op if no task is set."""
    task_id = _task_id.get()
    if not task_id:
        return
    record = {
        "ts": time.time(),
        "task_id": task_id,
        "event": event,
        **{k: _truncate(v) for k, v in fields.items()},
    }
    path = _TRACE_DIR / f"{task_id}.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("llm_trace: write failed for %s: %s", path, exc)
