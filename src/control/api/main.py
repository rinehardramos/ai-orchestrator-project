"""Worker API — HTTP front for worker CRUD + task dispatch + status.

Thin FastAPI wrapper over the existing in-process Python mechanisms
(``TaskScheduler``, ``config_db``, ``offline_queue.db``) so any client
with an API key can manage specializations and dispatch tasks without
importing project internals.

Runs as the ``worker-api`` service in the control plane docker-compose.

Auth: static ``X-Control-API-Key`` header. The key is read from the
``CONTROL_API_KEY`` env var at startup; requests without it or with a
mismatched key get 401.
"""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

log = logging.getLogger("worker_api")

app = FastAPI(title="Worker API", version="0.1.0")

_OFFLINE_DB = Path(
    os.environ.get(
        "OFFLINE_QUEUE_DB",
        str(Path(__file__).resolve().parents[3] / "data" / "offline_queue.db"),
    )
)


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────
def require_api_key(x_control_api_key: Optional[str] = Header(default=None)) -> str:
    expected = os.environ.get("CONTROL_API_KEY")
    if not expected:
        # Hard-fail rather than ship a blank-auth endpoint.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CONTROL_API_KEY not configured on server",
        )
    if not x_control_api_key or not secrets.compare_digest(
        x_control_api_key, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Control-API-Key",
        )
    return x_control_api_key


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class WorkerSpec(BaseModel):
    name: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    allowed_tools: list[str] = Field(default_factory=list)


class WorkerList(BaseModel):
    workers: list[WorkerSpec]
    count: int


class DispatchRequest(BaseModel):
    specialization: str = Field(..., min_length=1)
    task_description: str = Field(..., min_length=1)
    max_tool_calls: int = Field(default=50, gt=0)
    max_cost_usd: float = Field(default=0.50, gt=0)


class DispatchResponse(BaseModel):
    task_id: str
    specialization: str
    status: str


class TaskStatus(BaseModel):
    task_id: str
    found: bool
    history: Optional[dict[str, Any]] = None
    offline_queue: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_specializations() -> dict[str, Any]:
    from src.config_db import get_loader

    return dict(get_loader().load_namespace("specializations") or {})


def _save_specializations(ns: dict[str, Any]) -> None:
    from src.config_db import get_loader

    get_loader().save_namespace("specializations", ns)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "worker-api"}


@app.get("/workers", response_model=WorkerList)
def list_workers(_: str = Depends(require_api_key)) -> WorkerList:
    try:
        ns = _load_specializations()
    except Exception as exc:
        log.exception("list_workers failed")
        raise HTTPException(status_code=500, detail=f"config load failed: {exc}") from exc
    workers = [
        WorkerSpec(
            name=name,
            model=cfg.get("model", ""),
            provider=cfg.get("provider", ""),
            allowed_tools=cfg.get("allowed_tools") or [],
        )
        for name, cfg in sorted(ns.items())
        if isinstance(cfg, dict)
    ]
    return WorkerList(workers=workers, count=len(workers))


@app.post("/workers", response_model=WorkerSpec)
def upsert_worker(
    spec: WorkerSpec, _: str = Depends(require_api_key)
) -> WorkerSpec:
    try:
        ns = _load_specializations()
        ns[spec.name] = {
            "model": spec.model,
            "provider": spec.provider,
            "allowed_tools": spec.allowed_tools,
        }
        _save_specializations(ns)
    except Exception as exc:
        log.exception("upsert_worker failed")
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}") from exc
    return spec


@app.delete("/workers/{name}")
def delete_worker(
    name: str, _: str = Depends(require_api_key)
) -> dict[str, Any]:
    try:
        ns = _load_specializations()
        if name not in ns:
            raise HTTPException(status_code=404, detail=f"worker {name!r} not found")
        ns.pop(name)
        _save_specializations(ns)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("delete_worker failed")
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}") from exc
    return {"name": name, "deleted": True}


@app.post("/tasks", response_model=DispatchResponse)
async def dispatch_task(
    req: DispatchRequest, _: str = Depends(require_api_key)
) -> DispatchResponse:
    # Verify the specialization exists before dispatching.
    try:
        ns = _load_specializations()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"config load failed: {exc}") from exc
    if req.specialization not in ns:
        raise HTTPException(
            status_code=400,
            detail=f"unknown specialization {req.specialization!r}; known: {sorted(ns.keys())}",
        )

    try:
        from src.control.orchestrator.scheduler import TaskScheduler

        scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
        task_id = await scheduler.submit_agent_task(
            task_description=req.task_description,
            analysis_result={"specialization": req.specialization},
            max_tool_calls=req.max_tool_calls,
            max_cost_usd=req.max_cost_usd,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("dispatch_task failed")
        raise HTTPException(status_code=500, detail=f"dispatch failed: {exc}") from exc

    return DispatchResponse(
        task_id=task_id, specialization=req.specialization, status="submitted"
    )


@app.get("/tasks/{task_id}", response_model=TaskStatus)
def get_task_status(
    task_id: str, _: str = Depends(require_api_key)
) -> TaskStatus:
    if not _OFFLINE_DB.exists():
        return TaskStatus(task_id=task_id, found=False, reason="no offline_queue.db")

    history_row = None
    offline_row = None
    try:
        conn = sqlite3.connect(str(_OFFLINE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
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
        return TaskStatus(task_id=task_id, found=False)
    return TaskStatus(
        task_id=task_id,
        found=True,
        history={k: history_row[k] for k in history_row.keys()} if history_row else None,
        offline_queue={k: offline_row[k] for k in offline_row.keys()} if offline_row else None,
    )
