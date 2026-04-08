"""Pure-python handlers for the workers MCP server.

Kept transport-free so they can be imported and called directly from
Python code or tests without spawning a subprocess. The stdio MCP
wrapper lives in :mod:`mcp_server`.

Scope (v1): five tools that compose a real loop — list specializations,
create one, dispatch a task to one, poll status, and a sugar wrapper
for the common AGENT INSTRUCTIONS note flow.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_OFFLINE_DB = (
    Path(__file__).resolve().parents[2] / "data" / "offline_queue.db"
)


def _offline_db_path() -> Path:
    return _OFFLINE_DB


class WorkersHandlers:
    """Handlers for worker CRUD + dispatch + status tools."""

    def __init__(self, default_vault_path: Optional[str] = None) -> None:
        self.default_vault_path = default_vault_path or os.path.expanduser(
            "~/Projects/obsidian-notes/obsidian-notes"
        )

    # ------------------------------------------------------------------
    # list_workers
    # ------------------------------------------------------------------
    def list_workers(self) -> dict[str, Any]:
        """Return all specializations from the ``specializations`` DB namespace."""
        try:
            from src.config_db import get_loader

            ns = get_loader().load_namespace("specializations") or {}
        except Exception as exc:
            raise RuntimeError(f"Could not load specializations: {exc}") from exc
        workers = []
        for name, cfg in ns.items():
            if not isinstance(cfg, dict):
                continue
            workers.append(
                {
                    "name": name,
                    "model": cfg.get("model"),
                    "provider": cfg.get("provider"),
                    "allowed_tools": cfg.get("allowed_tools") or [],
                }
            )
        workers.sort(key=lambda w: w["name"])
        return {"workers": workers, "count": len(workers)}

    # ------------------------------------------------------------------
    # create_worker (upsert)
    # ------------------------------------------------------------------
    def create_worker(
        self,
        name: str,
        model: str,
        provider: str,
        allowed_tools: list[str],
    ) -> dict[str, Any]:
        """Create or replace a specialization in the shared namespace.

        Same name = upsert (the existing row is overwritten).
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")
        if not isinstance(allowed_tools, list) or not all(
            isinstance(t, str) for t in allowed_tools
        ):
            raise ValueError("allowed_tools must be a list of strings")

        try:
            from src.config_db import get_loader

            loader = get_loader()
            ns = dict(loader.load_namespace("specializations") or {})
            existed = name in ns
            ns[name] = {
                "model": model,
                "provider": provider,
                "allowed_tools": allowed_tools,
            }
            loader.save_namespace("specializations", ns)
        except Exception as exc:
            raise RuntimeError(f"Could not persist worker: {exc}") from exc
        return {
            "name": name,
            "model": model,
            "provider": provider,
            "allowed_tools": allowed_tools,
            "action": "updated" if existed else "created",
        }

    # ------------------------------------------------------------------
    # dispatch_worker
    # ------------------------------------------------------------------
    async def dispatch_worker(
        self,
        specialization: str,
        task_description: str,
        max_tool_calls: int = 50,
        max_cost_usd: float = 0.50,
    ) -> dict[str, Any]:
        """Submit an agent task routed to the given specialization."""
        if not isinstance(specialization, str) or not specialization.strip():
            raise ValueError("specialization must be a non-empty string")
        if not isinstance(task_description, str) or not task_description.strip():
            raise ValueError("task_description must be a non-empty string")
        if not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be a positive integer")
        if not isinstance(max_cost_usd, (int, float)) or max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be positive")

        # Verify the specialization exists before dispatching. This catches
        # typos that would otherwise silently fall back to 'general'.
        known = self.list_workers()["workers"]
        if not any(w["name"] == specialization for w in known):
            raise ValueError(
                f"Unknown specialization {specialization!r}. "
                f"Known: {[w['name'] for w in known]}"
            )

        from src.control.orchestrator.scheduler import TaskScheduler

        scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
        task_id = await scheduler.submit_agent_task(
            task_description=task_description,
            analysis_result={"specialization": specialization},
            max_tool_calls=max_tool_calls,
            max_cost_usd=max_cost_usd,
        )
        return {
            "task_id": task_id,
            "specialization": specialization,
            "status": "submitted",
        }

    # ------------------------------------------------------------------
    # get_task_status
    # ------------------------------------------------------------------
    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Look up a task by id in the local offline queue sqlite db.

        v1 is sqlite-only: reports submission metadata tracked by the
        TaskScheduler (task_history + offline_tasks). For live workflow
        status, query Temporal directly by task_id — this handler does
        not reach out to Temporal to keep the MCP cheap and synchronous.
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        db_path = _offline_db_path()
        if not db_path.exists():
            return {"task_id": task_id, "found": False, "reason": "no offline_queue.db"}

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            history_row = None
            offline_row = None
            try:
                cur.execute(
                    "SELECT * FROM task_history WHERE task_id = ? LIMIT 1", (task_id,)
                )
                history_row = cur.fetchone()
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute(
                    "SELECT * FROM offline_tasks WHERE task_id = ? LIMIT 1", (task_id,)
                )
                offline_row = cur.fetchone()
            except sqlite3.OperationalError:
                pass
        finally:
            try:
                conn.close()  # type: ignore[has-type]
            except Exception:
                pass

        if not history_row and not offline_row:
            return {"task_id": task_id, "found": False}

        result: dict[str, Any] = {"task_id": task_id, "found": True}
        if history_row:
            result["history"] = {k: history_row[k] for k in history_row.keys()}
        if offline_row:
            result["offline_queue"] = {k: offline_row[k] for k in offline_row.keys()}
        return result

    # ------------------------------------------------------------------
    # run_assistant (sugar)
    # ------------------------------------------------------------------
    async def run_assistant(
        self, note: str = "AGENT INSTRUCTIONS.md"
    ) -> dict[str, Any]:
        """Load a note from the Obsidian vault and dispatch it to 'assistant'."""
        from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor

        ingestor = ObsidianVaultIngestor(vault_path=self.default_vault_path)
        chunks = ingestor.get_note(note)
        if not chunks:
            raise LookupError(
                f"Note {note!r} not found in the obsidian vault collection. "
                f"Sync it first: python -m src.ingestion.obsidian sync"
            )
        instructions = "\n\n".join(c.get("content", "") for c in chunks).strip()
        if not instructions:
            raise LookupError(f"Note {note!r} is empty after concatenation")

        result = await self.dispatch_worker(
            specialization="assistant",
            task_description=instructions,
        )
        result["note"] = note
        result["instructions_chars"] = len(instructions)
        return result
