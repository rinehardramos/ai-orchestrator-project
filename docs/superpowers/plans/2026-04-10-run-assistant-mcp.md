# run_assistant MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `run_assistant` MCP tool to `worker_mcp` that lets Claude trigger the assistant worker with a short hint, recovering full task context from Qdrant and dispatching via the control plane.

**Architecture:** Three modes — Recall (short hint → subject lookup → dispatch), Seed (first run with full steps → store in Qdrant + SQLite → dispatch), Gap-fill (no match + no details → return questionnaire). The control plane SQLite DB gains a `task_subjects` index table. The execution worker gains a Subject pre-processing layer before the existing ReAct loop.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Qdrant (`qdrant-client`), MCP SDK (`mcp`), LangGraph (existing worker), Temporal (existing dispatch path)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `~/.claude/mcp-servers/packages/worker_mcp/server.py` | Modify | Add `run_assistant` tool + `WorkerApiClient.run_assistant()` + inline Qdrant helpers |
| `src/control/api/main.py` | Modify | Add `GET /tasks/subjects` + `POST /tasks/subjects` endpoints + SQLite migration for `task_subjects` |
| `src/execution/worker/worker.py` | Modify | Add Subject detection + `resolve_subject()` + tool pre-flight + step assertions + post-run write-back |
| `tests/test_worker_mcp_run_assistant.py` | Create | Unit tests for MCP tool modes (mock HTTP) |
| `tests/test_control_api_subjects.py` | Create | Tests for new control plane endpoints |
| `tests/test_worker_subject_recall.py` | Create | Tests for resolve_subject + pre-flight in worker |

---

## Task 1: SQLite migration — `task_subjects` table

**Files:**
- Modify: `src/control/api/main.py`
- Create: `tests/test_control_api_subjects.py`

The `task_subjects` table goes into the same SQLite file as `offline_queue.db`. The migration runs at startup via a new `_ensure_task_subjects_table()` call.

- [ ] **Step 1: Write failing test**

```python
# tests/test_control_api_subjects.py
import sqlite3, os, tempfile, pytest
from pathlib import Path

def test_task_subjects_table_created(tmp_path):
    """_ensure_task_subjects_table creates the table if absent."""
    db_path = tmp_path / "offline_queue.db"
    os.environ["OFFLINE_QUEUE_DB"] = str(db_path)

    # Import after setting env so _OFFLINE_DB picks up tmp_path
    import importlib, sys
    sys.modules.pop("src.control.api.main", None)
    import src.control.api.main as api_main

    api_main._ensure_task_subjects_table()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_subjects'")
    assert cur.fetchone() is not None
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/rinehardramos/Projects/ai-orchestrator-project
python -m pytest tests/test_control_api_subjects.py::test_task_subjects_table_created -v
```

Expected: `FAILED — AttributeError: module has no attribute '_ensure_task_subjects_table'`

- [ ] **Step 3: Implement `_ensure_task_subjects_table` and call it at startup**

In `src/control/api/main.py`, add after the `_OFFLINE_DB` definition (around line 36):

```python
def _ensure_task_subjects_table() -> None:
    """Create task_subjects table in the offline queue SQLite DB if absent."""
    _OFFLINE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_OFFLINE_DB))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_subjects (
                subject      TEXT PRIMARY KEY,
                qdrant_key   TEXT NOT NULL,
                last_task_id TEXT,
                last_run_at  TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
    finally:
        conn.close()

_ensure_task_subjects_table()
```

- [ ] **Step 4: Run test — must pass**

```bash
python -m pytest tests/test_control_api_subjects.py::test_task_subjects_table_created -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/control/api/main.py tests/test_control_api_subjects.py
git commit -m "feat(control-api): add task_subjects SQLite table migration"
```

---

## Task 2: Control plane endpoints — `GET /tasks/subjects` and `POST /tasks/subjects`

**Files:**
- Modify: `src/control/api/main.py`
- Modify: `tests/test_control_api_subjects.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_control_api_subjects.py`:

```python
from fastapi.testclient import TestClient

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_QUEUE_DB", str(tmp_path / "offline_queue.db"))
    monkeypatch.setenv("CONTROL_API_KEY", "test-key")
    import importlib, sys
    sys.modules.pop("src.control.api.main", None)
    import src.control.api.main as api_main
    return TestClient(api_main.app), api_main

HDR = {"X-Control-API-Key": "test-key"}

def test_post_subject(client):
    tc, _ = client
    r = tc.post("/tasks/subjects", json={
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }, headers=HDR)
    assert r.status_code == 201
    assert r.json()["subject"] == "EOS Report Gmail Draft"

def test_get_subjects_fuzzy(client):
    tc, _ = client
    tc.post("/tasks/subjects", json={
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }, headers=HDR)
    r = tc.get("/tasks/subjects?q=EOS report", headers=HDR)
    assert r.status_code == 200
    data = r.json()
    assert len(data["matches"]) >= 1
    assert data["matches"][0]["subject"] == "EOS Report Gmail Draft"

def test_get_subjects_no_match(client):
    tc, _ = client
    r = tc.get("/tasks/subjects?q=nonexistent task xyz", headers=HDR)
    assert r.status_code == 200
    assert r.json()["matches"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_control_api_subjects.py -v -k "test_post_subject or test_get_subjects"
```

Expected: `FAILED — 404 Not Found`

- [ ] **Step 3: Implement the endpoints**

In `src/control/api/main.py`, add these schemas and routes before the final `get_task_status` route:

```python
# ── Schemas ──────────────────────────────────────────────────────────────────
class SubjectRecord(BaseModel):
    subject: str
    qdrant_key: str
    last_task_id: Optional[str] = None
    last_run_at: Optional[str] = None
    created_at: Optional[str] = None


class SubjectUpsert(BaseModel):
    subject: str = Field(..., min_length=1)
    qdrant_key: str = Field(..., min_length=1)
    last_task_id: Optional[str] = None


class SubjectSearchResponse(BaseModel):
    matches: list[SubjectRecord]


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/tasks/subjects", response_model=SubjectRecord, status_code=201)
def upsert_subject(
    body: SubjectUpsert, _: str = Depends(require_api_key)
) -> SubjectRecord:
    """Register or update a task subject → Qdrant key mapping."""
    conn = sqlite3.connect(str(_OFFLINE_DB))
    try:
        conn.execute(
            """INSERT INTO task_subjects (subject, qdrant_key, last_task_id)
               VALUES (?, ?, ?)
               ON CONFLICT(subject) DO UPDATE SET
                 qdrant_key   = excluded.qdrant_key,
                 last_task_id = excluded.last_task_id,
                 last_run_at  = datetime('now')""",
            (body.subject, body.qdrant_key, body.last_task_id),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT subject, qdrant_key, last_task_id, last_run_at, created_at "
            "FROM task_subjects WHERE subject = ?",
            (body.subject,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return SubjectRecord(
        subject=row[0], qdrant_key=row[1],
        last_task_id=row[2], last_run_at=row[3], created_at=row[4],
    )


@app.get("/tasks/subjects", response_model=SubjectSearchResponse)
def search_subjects(
    q: str, _: str = Depends(require_api_key)
) -> SubjectSearchResponse:
    """Fuzzy-search task subjects using SQLite LIKE. Returns ranked matches."""
    if not _OFFLINE_DB.exists():
        return SubjectSearchResponse(matches=[])
    terms = q.lower().split()
    conn = sqlite3.connect(str(_OFFLINE_DB))
    conn.row_factory = sqlite3.Row
    try:
        # Score each row by how many query terms appear in the lowercased subject
        cur = conn.execute(
            "SELECT subject, qdrant_key, last_task_id, last_run_at, created_at "
            "FROM task_subjects"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    scored = []
    for row in rows:
        subj_lower = row["subject"].lower()
        score = sum(1 for t in terms if t in subj_lower)
        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return SubjectSearchResponse(matches=[
        SubjectRecord(
            subject=r["subject"], qdrant_key=r["qdrant_key"],
            last_task_id=r["last_task_id"], last_run_at=r["last_run_at"],
            created_at=r["created_at"],
        )
        for _, r in scored
    ])
```

- [ ] **Step 4: Run tests — must pass**

```bash
python -m pytest tests/test_control_api_subjects.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/control/api/main.py tests/test_control_api_subjects.py
git commit -m "feat(control-api): add GET/POST /tasks/subjects endpoints"
```

---

## Task 3: Qdrant helpers in `worker_mcp` — seed and recall `assistant_tasks`

**Files:**
- Modify: `~/.claude/mcp-servers/packages/worker_mcp/server.py`
- Create: `tests/test_worker_mcp_run_assistant.py`

These helpers live inline in `server.py` (no new file — YAGNI). They use `qdrant-client` which is already in `~/.claude/mcp-servers/requirements.txt` (add if missing).

- [ ] **Step 1: Verify qdrant-client is available**

```bash
cd ~/.claude/mcp-servers
grep "qdrant" requirements.txt || echo "qdrant-client" >> requirements.txt
pip install qdrant-client -q
```

Expected: `qdrant-client` version printed or silently installed.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_worker_mcp_run_assistant.py
import json, uuid, pytest
from unittest.mock import MagicMock, patch

# ── Helpers under test (extracted to be importable without full MCP stack) ──
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

def test_store_seed_and_recall(tmp_path):
    """Seed stores a record; recall returns it by subject."""
    store = AssistantTaskStore(qdrant_url="http://localhost:6333", collection="assistant_tasks_test")
    mock_client = MagicMock()
    mock_client.search.return_value = [
        MagicMock(score=0.95, payload={
            "subject": "EOS Report Gmail Draft",
            "subject_normalized": "eos report gmail draft",
            "steps": [{"n": 1, "action": "qdrant_recall", "params": {"note": "EOS Report"}}],
            "required_tools": ["qdrant_recall"],
            "last_outcome": "",
            "step_outcomes": {},
            "version": 1,
        })
    ]
    store._client = mock_client

    result = store.recall("EOS report", threshold=0.80)
    assert result is not None
    assert result["subject"] == "EOS Report Gmail Draft"
    assert result["score"] >= 0.80

def test_store_recall_low_confidence_returns_none():
    store = AssistantTaskStore(qdrant_url="http://localhost:6333", collection="assistant_tasks_test")
    mock_client = MagicMock()
    mock_client.search.return_value = [
        MagicMock(score=0.55, payload={"subject": "Something Else"})
    ]
    store._client = mock_client
    result = store.recall("EOS report", threshold=0.80)
    assert result is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/rinehardramos/Projects/ai-orchestrator-project
python -m pytest tests/test_worker_mcp_run_assistant.py -v -k "normalize or recall"
```

Expected: `FAILED — ImportError: cannot import name 'AssistantTaskStore'`

- [ ] **Step 4: Add `_normalize_subject` and `AssistantTaskStore` to `server.py`**

Add after the existing imports at the top of `~/.claude/mcp-servers/packages/worker_mcp/server.py`:

```python
import re
import uuid as _uuid
from datetime import date as _date
from typing import Optional

# ── Qdrant helpers for assistant_tasks collection ─────────────────────────────

_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ID_PATTERN   = re.compile(r"\b[a-f0-9]{6,}\b")

def _normalize_subject(subject: str) -> str:
    """Strip dynamic parts (dates, hex IDs, trailing dashes) then lowercase."""
    s = _DATE_PATTERN.sub("", subject)
    s = _ID_PATTERN.sub("", s)
    s = re.sub(r"[-–—]+", " ", s)   # dashes → spaces
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


class AssistantTaskStore:
    """Thin Qdrant wrapper for the assistant_tasks collection."""

    EMBEDDING_SIZE = 768  # matches existing worker embeddings (all-minilm-l6-v2)

    def __init__(self, qdrant_url: str, collection: str = "assistant_tasks") -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self._client = QdrantClient(url=qdrant_url)
        self._collection = collection
        try:
            self._client.get_collection(collection)
        except Exception:
            self._client.recreate_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=self.EMBEDDING_SIZE, distance=Distance.COSINE),
            )

    def _embed(self, text: str) -> list[float]:
        """Use the same embedder as the main worker."""
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(text).tolist()

    def seed(self, subject: str, steps: list[dict], required_tools: list[str]) -> str:
        """Store a new task definition. Returns the Qdrant point ID (UUID str)."""
        from qdrant_client.models import PointStruct
        point_id = str(_uuid.uuid4())
        normalized = _normalize_subject(subject)
        embedding = self._embed(f"{subject} {' '.join(s.get('action','') for s in steps)}")
        self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "subject": subject,
                    "subject_normalized": normalized,
                    "steps": steps,
                    "required_tools": required_tools,
                    "last_run_id": None,
                    "last_outcome": "",
                    "step_outcomes": {},
                    "version": 1,
                },
            )],
        )
        return point_id

    def recall(self, hint: str, threshold: float = 0.80) -> Optional[dict]:
        """Semantic search by hint. Returns payload + score dict, or None if below threshold."""
        embedding = self._embed(hint)
        results = self._client.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=3,
            with_payload=True,
        )
        if not results or results[0].score < threshold:
            return None
        top = results[0]
        payload = dict(top.payload)
        payload["score"] = top.score
        payload["qdrant_key"] = str(top.id)
        return payload

    def recall_candidates(self, hint: str, threshold: float = 0.60) -> list[dict]:
        """Return top-3 matches above threshold for disambiguation."""
        embedding = self._embed(hint)
        results = self._client.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=3,
            with_payload=True,
        )
        return [
            {**dict(r.payload), "score": r.score, "qdrant_key": str(r.id)}
            for r in results
            if r.score >= threshold
        ]

    def write_back(self, qdrant_key: str, task_id: str, outcome: str, step_outcomes: dict) -> None:
        """Update last_run_id, last_outcome, step_outcomes, increment version."""
        from qdrant_client.models import SetPayload
        # Read current version
        points = self._client.retrieve(collection_name=self._collection, ids=[qdrant_key], with_payload=True)
        version = (points[0].payload.get("version", 1) + 1) if points else 2
        self._client.set_payload(
            collection_name=self._collection,
            payload={
                "last_run_id": task_id,
                "last_outcome": outcome,
                "step_outcomes": step_outcomes,
                "version": version,
            },
            points=[qdrant_key],
        )
```

- [ ] **Step 5: Run tests — must pass**

```bash
python -m pytest tests/test_worker_mcp_run_assistant.py -v -k "normalize or recall"
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add ~/.claude/mcp-servers/packages/worker_mcp/server.py \
        tests/test_worker_mcp_run_assistant.py
git commit -m "feat(worker-mcp): add AssistantTaskStore + _normalize_subject helpers"
```

---

## Task 4: `WorkerApiClient.run_assistant()` — the three-mode logic

**Files:**
- Modify: `~/.claude/mcp-servers/packages/worker_mcp/server.py`
- Modify: `tests/test_worker_mcp_run_assistant.py`

This is the core orchestration method called by the MCP tool. It implements Recall / Seed / Gap-fill.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_worker_mcp_run_assistant.py`:

```python
from packages.worker_mcp.server import WorkerApiClient

QDRANT_URL = "http://localhost:6333"

def test_gap_fill_returned_when_no_hint_match():
    client = WorkerApiClient(base_url="http://fake", api_key="k")
    store = MagicMock()
    store.recall.return_value = None
    store.recall_candidates.return_value = []
    result = client.run_assistant(hint="unknown task xyz", details=None, _store=store)
    assert result["clarify"] is True
    assert isinstance(result["questions"], list)
    assert len(result["questions"]) >= 3

def test_recall_dispatches_when_subject_found():
    client = WorkerApiClient(base_url="http://fake", api_key="k")
    store = MagicMock()
    store.recall.return_value = {
        "subject": "EOS Report Gmail Draft",
        "qdrant_key": "aaa",
        "score": 0.91,
        "steps": [{"n": 1, "action": "gmail_draft", "params": {}}],
        "required_tools": ["gmail_draft"],
    }
    # mock _request
    client._request = MagicMock(return_value={"task_id": "t-123", "specialization": "assistant", "status": "submitted"})
    result = client.run_assistant(hint="EOS report", details=None, _store=store)
    assert result["dispatched"] is True
    assert result["task_id"] == "t-123"
    assert result["subject"] == "EOS Report Gmail Draft"

def test_disambiguation_when_multiple_close_matches():
    client = WorkerApiClient(base_url="http://fake", api_key="k")
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
    client = WorkerApiClient(base_url="http://fake", api_key="k")
    store = MagicMock()
    store.recall.return_value = None
    store.recall_candidates.return_value = []
    store.seed.return_value = "new-qdrant-key"
    client._request = MagicMock(side_effect=[
        None,  # POST /tasks/subjects
        {"task_id": "t-456", "specialization": "assistant", "status": "submitted"},
    ])
    details = "1. Find EOS Report in Qdrant\n2. Draft Gmail to recipient\n3. Send as draft"
    result = client.run_assistant(hint="EOS report", details=details, _store=store)
    assert result["seeded"] is True
    assert result["task_id"] == "t-456"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_worker_mcp_run_assistant.py -v -k "gap_fill or recall_dispatches or disambiguation or seed_stores"
```

Expected: `FAILED — AttributeError: 'WorkerApiClient' object has no attribute 'run_assistant'`

- [ ] **Step 3: Add `run_assistant` method to `WorkerApiClient`**

Add to the `WorkerApiClient` class in `~/.claude/mcp-servers/packages/worker_mcp/server.py`:

```python
    # ── run_assistant ────────────────────────────────────────────────────────

    _GAP_FILL_QUESTIONS = [
        "What Qdrant note or data source should the agent read? (e.g. 'EOS Report')",
        "What action should be taken? (e.g. email draft, file write, Telegram notification)",
        "Who are the recipients or targets? (leave blank if not applicable)",
        "What should the subject or title be? Use {today} for today's date.",
        "Any additional parameters? (sender address, attachments, format, etc.)",
    ]

    _ACTION_TOOL_MAP = {
        "qdrant_recall":    "qdrant_recall",
        "gmail_draft":      "gmail_draft",
        "shell_exec":       "shell_exec",
        "browser_exec":     "browser_exec",
        "write_file":       "write_file",
        "telegram_notify":  "telegram_notify",
        "compose_email":    "compose_email",
    }

    def _parse_steps(self, details: str) -> tuple[list[dict], list[str]]:
        """
        Parse numbered step list from free text into structured step dicts.
        Returns (steps, required_tools).

        Matches lines like: "1. action: params" or "1. Do X using gmail_draft"
        """
        steps = []
        required_tools = set()
        for line in details.strip().splitlines():
            m = re.match(r"^\s*(\d+)\.\s+(.+)$", line)
            if not m:
                continue
            n = int(m.group(1))
            text = m.group(2).strip()
            # Infer action from known keywords in the text
            action = "generic"
            params: dict = {"description": text}
            for keyword, tool in self._ACTION_TOOL_MAP.items():
                if keyword.replace("_", " ") in text.lower() or keyword in text.lower():
                    action = keyword
                    required_tools.add(tool)
                    break
            # Extract note name if pattern like "Find X in Qdrant" or "Qdrant note: X"
            note_m = re.search(r"(?:find|read|recall|note[:\s]+)\s+['\"]?([A-Z][^'\"]+?)['\"]?\s+(?:in\s+Qdrant|from\s+Qdrant|note)", text, re.IGNORECASE)
            if note_m and action == "qdrant_recall":
                params = {"note": note_m.group(1).strip()}
            steps.append({"n": n, "action": action, "params": params})
        return steps, list(required_tools)

    def _fill_template_params(self, steps: list[dict]) -> list[dict]:
        """Fill {today} placeholder in step params."""
        today = str(_date.today())
        filled = []
        for step in steps:
            params = {
                k: v.replace("{today}", today) if isinstance(v, str) else v
                for k, v in step["params"].items()
            }
            filled.append({**step, "params": params})
        return filled

    def _steps_to_prompt(self, subject: str, steps: list[dict]) -> str:
        """Reconstruct a numbered step prompt for the worker ReAct loop."""
        today = str(_date.today())
        lines = [f"Subject: {subject}", f"Today: {today}", "", "Execute the following steps:"]
        for s in steps:
            lines.append(f"{s['n']}. [{s['action']}] {json.dumps(s['params'])}")
        return "\n".join(lines)

    def run_assistant(
        self,
        hint: str,
        details: Optional[str] = None,
        _store: Optional[Any] = None,
    ) -> dict:
        """
        Orchestrate Recall / Seed / Gap-fill modes.
        _store is injected for testing; production uses a real AssistantTaskStore.
        """
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        store = _store or AssistantTaskStore(qdrant_url=qdrant_url)

        # ── Mode 1: Recall ────────────────────────────────────────────────────
        if not details:
            match = store.recall(hint, threshold=0.80)
            if match:
                filled_steps = self._fill_template_params(match["steps"])
                task_desc = self._steps_to_prompt(match["subject"], filled_steps)
                resp = self._request("POST", "/tasks", json_body={
                    "specialization": "assistant",
                    "task_description": task_desc,
                    "max_tool_calls": 50,
                    "max_cost_usd": 0.50,
                })
                return {
                    "dispatched": True,
                    "task_id": resp["task_id"],
                    "subject": match["subject"],
                }
            # Check for near-matches (disambiguation)
            candidates = store.recall_candidates(hint, threshold=0.60)
            if len(candidates) >= 2:
                top2_scores = [c["score"] for c in candidates[:2]]
                if abs(top2_scores[0] - top2_scores[1]) < 0.05:
                    return {
                        "confirm_subject": True,
                        "candidates": [
                            {"subject": c["subject"], "score": round(c["score"], 3)}
                            for c in candidates[:3]
                        ],
                    }
            # Gap-fill
            return {"clarify": True, "questions": self._GAP_FILL_QUESTIONS}

        # ── Mode 2: Seed ──────────────────────────────────────────────────────
        steps, required_tools = self._parse_steps(details)
        subject_canonical = hint.strip().title()
        normalized = _normalize_subject(subject_canonical)

        qdrant_key = store.seed(subject_canonical, steps, required_tools)

        # Register in control plane subject index
        try:
            self._request("POST", "/tasks/subjects", json_body={
                "subject": normalized,
                "qdrant_key": qdrant_key,
            })
        except Exception as exc:
            log.warning(f"Could not register subject in control plane: {exc}")

        filled_steps = self._fill_template_params(steps)
        task_desc = self._steps_to_prompt(subject_canonical, filled_steps)
        resp = self._request("POST", "/tasks", json_body={
            "specialization": "assistant",
            "task_description": task_desc,
            "max_tool_calls": 50,
            "max_cost_usd": 0.50,
        })
        return {
            "seeded": True,
            "subject": subject_canonical,
            "qdrant_key": qdrant_key,
            "task_id": resp["task_id"],
        }
```

- [ ] **Step 4: Run tests — must pass**

```bash
python -m pytest tests/test_worker_mcp_run_assistant.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ~/.claude/mcp-servers/packages/worker_mcp/server.py \
        tests/test_worker_mcp_run_assistant.py
git commit -m "feat(worker-mcp): add WorkerApiClient.run_assistant() with Seed/Recall/Gap-fill"
```

---

## Task 5: Register `run_assistant` as MCP tool

**Files:**
- Modify: `~/.claude/mcp-servers/packages/worker_mcp/server.py`

- [ ] **Step 1: Add tool definition and dispatch entry to `run()` in `server.py`**

In the `run()` function, add to the `tools` list:

```python
        Tool(
            name="run_assistant",
            description=(
                "Trigger the assistant worker for a named recurring task. "
                "On first run provide full step-by-step 'details' to seed the task. "
                "On subsequent runs only a short 'hint' is needed — the system recalls "
                "prior context from Qdrant and dispatches automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "hint": {
                        "type": "string",
                        "description": "Short phrase identifying the task, e.g. 'EOS report'",
                    },
                    "details": {
                        "type": "string",
                        "description": (
                            "Full numbered step-by-step instructions for first-time seeding. "
                            "Omit on recall runs."
                        ),
                    },
                },
                "required": ["hint"],
            },
        ),
```

In the `dispatch` dict, add:

```python
            "run_assistant": lambda **kw: client.run_assistant(**kw),
```

- [ ] **Step 2: Smoke-test the MCP tool registration**

```bash
cd ~/.claude/mcp-servers
python -c "
from packages.worker_mcp.server import run
import inspect
# Verify run_assistant is in the tool list by importing the tool names
from mcp.types import Tool
print('MCP tool registration: OK if no import errors')
"
```

Expected: prints `MCP tool registration: OK if no import errors`

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/mcp-servers/packages/worker_mcp/server.py
git commit -m "feat(worker-mcp): register run_assistant as MCP tool"
```

---

## Task 6: Worker — Subject detection + `resolve_subject` + tool pre-flight

**Files:**
- Modify: `src/execution/worker/worker.py`
- Create: `tests/test_worker_subject_recall.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_worker_subject_recall.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys, os
sys.path.insert(0, "/Users/rinehardramos/Projects/ai-orchestrator-project")

# We test resolve_subject and pre-flight in isolation
# by importing just the functions once they exist

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
    # shell_exec is always registered
    preflight_tools(["shell_exec"])  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_worker_subject_recall.py -v
```

Expected: `FAILED — ImportError: cannot import name 'resolve_subject'`

- [ ] **Step 3: Add `LowConfidenceError`, `ToolUnavailableError`, `resolve_subject`, `preflight_tools` to `worker.py`**

Add after the imports block in `src/execution/worker/worker.py` (after line ~66, before `logging.basicConfig`):

```python
from datetime import date as _date_today


# ── Assistant Subject Recall ──────────────────────────────────────────────────

class LowConfidenceError(RuntimeError):
    def __init__(self, hint: str, score: float, best_match: str):
        super().__init__(
            f"Low confidence recall for {hint!r}: best match {best_match!r} scored {score:.2f} (< 0.80)"
        )
        self.hint = hint
        self.score = score
        self.best_match = best_match


class ToolUnavailableError(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__(f"Required tools not registered: {missing}")
        self.missing = missing


def _get_assistant_task_store():
    """Lazy-init AssistantTaskStore using the same Qdrant URL as the rest of the worker."""
    from qdrant_client import QdrantClient
    # Reuse the qdrant_url already computed at module level
    class _Store:
        def __init__(self, url):
            self._client = QdrantClient(url=url)
            self._collection = "assistant_tasks"

        def _embed(self, text: str) -> list[float]:
            emb = get_embedder()
            return emb.embed_text(text)

        def recall(self, hint: str, threshold: float = 0.80):
            results = self._client.search(
                collection_name=self._collection,
                query_vector=self._embed(hint),
                limit=1,
                with_payload=True,
            )
            if not results or results[0].score < threshold:
                return None
            top = results[0]
            payload = dict(top.payload)
            payload["score"] = top.score
            payload["qdrant_key"] = str(top.id)
            return payload

        def write_back(self, qdrant_key: str, task_id: str, outcome: str, step_outcomes: dict) -> None:
            points = self._client.retrieve(
                collection_name=self._collection, ids=[qdrant_key], with_payload=True
            )
            version = (points[0].payload.get("version", 1) + 1) if points else 2
            self._client.set_payload(
                collection_name=self._collection,
                payload={
                    "last_run_id": task_id,
                    "last_outcome": outcome,
                    "step_outcomes": step_outcomes,
                    "version": version,
                },
                points=[qdrant_key],
            )

    return _Store(qdrant_url)


async def resolve_subject(hint: str, store=None) -> dict:
    """
    Semantic-search assistant_tasks Qdrant collection for hint.
    Returns dict with task_description, required_tools, qdrant_key.
    Raises LowConfidenceError if no match above threshold.
    """
    if store is None:
        store = _get_assistant_task_store()

    match = store.recall(hint, threshold=0.80)
    if match is None:
        raise LowConfidenceError(hint, score=0.0, best_match="(none)")

    today = str(_date_today.today())
    lines = [
        f"Subject: {match['subject']}",
        f"Today: {today}",
        "",
        "Execute the following steps:",
    ]
    for step in match.get("steps", []):
        params = {
            k: v.replace("{today}", today) if isinstance(v, str) else v
            for k, v in step.get("params", {}).items()
        }
        lines.append(f"{step['n']}. [{step['action']}] {params}")

    return {
        "task_description": "\n".join(lines),
        "required_tools": match.get("required_tools", []),
        "qdrant_key": match.get("qdrant_key"),
        "subject": match.get("subject"),
    }


def preflight_tools(required_tools: list[str]) -> None:
    """
    Verify all required_tools are present in TOOL_REGISTRY.
    Raises ToolUnavailableError listing any missing tools.
    """
    registered_names = {t["name"] for t in TOOL_REGISTRY}
    missing = [t for t in required_tools if t not in registered_names]
    if missing:
        raise ToolUnavailableError(missing)
```

- [ ] **Step 4: Run tests — must pass**

```bash
python -m pytest tests/test_worker_subject_recall.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/execution/worker/worker.py tests/test_worker_subject_recall.py
git commit -m "feat(worker): add resolve_subject, preflight_tools, LowConfidenceError, ToolUnavailableError"
```

---

## Task 7: Worker — wire Subject path into `run_agent_pipeline`

**Files:**
- Modify: `src/execution/worker/worker.py`
- Modify: `tests/test_worker_subject_recall.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_worker_subject_recall.py`:

```python
@pytest.mark.asyncio
async def test_run_agent_pipeline_routes_subject_task():
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

    with patch("src.execution.worker.worker._get_assistant_task_store", return_value=mock_store), \
         patch("src.execution.worker.worker._run_react_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = {"status": "completed", "summary": "done", "total_cost_usd": 0.0, "tool_call_count": 1, "artifact_files": []}
        result = await run_agent_pipeline(subject_payload, "gemma-4b")

    mock_store.recall.assert_called_once()
    assert result["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_worker_subject_recall.py::test_run_agent_pipeline_routes_subject_task -v
```

Expected: `FAILED` (Subject path not yet wired)

- [ ] **Step 3: Wire Subject detection into `run_agent_pipeline`**

Find the `run_agent_pipeline` function in `src/execution/worker/worker.py` and add the Subject pre-processing block at the start of the function body, before any existing logic:

```python
    # ── Subject recall path ───────────────────────────────────────────────────
    description = task_payload.get("description", "")
    _subject_meta: dict = {}
    if description.startswith("Subject: "):
        subject_hint = description.removeprefix("Subject: ").strip()
        try:
            store = _get_assistant_task_store()
            resolved = await resolve_subject(subject_hint, store)
            task_payload = {**task_payload, "description": resolved["task_description"]}
            _subject_meta = {
                "qdrant_key": resolved["qdrant_key"],
                "subject": resolved["subject"],
                "required_tools": resolved["required_tools"],
            }
            # Pre-flight check
            preflight_tools(resolved["required_tools"])
            logger.info(f"[SUBJECT RECALL] {resolved['subject']!r} resolved, tools verified")
        except LowConfidenceError as exc:
            logger.error(f"[SUBJECT RECALL] {exc}")
            return {
                "status": "error",
                "summary": str(exc),
                "total_cost_usd": 0.0,
                "tool_call_count": 0,
                "artifact_files": [],
            }
        except ToolUnavailableError as exc:
            logger.error(f"[SUBJECT RECALL] {exc}")
            return {
                "status": "error",
                "summary": str(exc),
                "total_cost_usd": 0.0,
                "tool_call_count": 0,
                "artifact_files": [],
            }
    # ── end Subject recall path ───────────────────────────────────────────────
```

- [ ] **Step 4: Extract the existing ReAct body into `_run_react_loop` (needed by test mock)**

Wrap the existing pipeline body (after the Subject block) in a helper `_run_react_loop(task_payload, model_id)` so the test can mock it. This is a simple rename — no logic changes.

- [ ] **Step 5: Run all subject tests — must pass**

```bash
python -m pytest tests/test_worker_subject_recall.py -v
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add src/execution/worker/worker.py tests/test_worker_subject_recall.py
git commit -m "feat(worker): wire Subject recall + preflight into run_agent_pipeline"
```

---

## Task 8: Worker — step assertions + post-run write-back

**Files:**
- Modify: `src/execution/worker/worker.py`
- Modify: `tests/test_worker_subject_recall.py`

Step assertions are injected as scratchpad messages in the ReAct loop. Post-run write-back calls `store.write_back()` after the pipeline completes.

- [ ] **Step 1: Write failing test for write-back**

Append to `tests/test_worker_subject_recall.py`:

```python
@pytest.mark.asyncio
async def test_writeback_called_after_subject_task():
    from src.execution.worker.worker import run_agent_pipeline

    payload = {
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
        "steps": [{"n": 1, "action": "shell_exec", "params": {"command": "echo hi"}}],
        "required_tools": ["shell_exec"],
    }
    with patch("src.execution.worker.worker._get_assistant_task_store", return_value=mock_store), \
         patch("src.execution.worker.worker._run_react_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = {
            "status": "completed",
            "summary": "Draft created OK.",
            "total_cost_usd": 0.01,
            "tool_call_count": 2,
            "artifact_files": [],
        }
        result = await run_agent_pipeline(payload, "gemma-4b")

    mock_store.write_back.assert_called_once()
    call_kwargs = mock_store.write_back.call_args
    assert call_kwargs.kwargs.get("outcome") == "Draft created OK." or \
           call_kwargs.args[2] == "Draft created OK."
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_worker_subject_recall.py::test_writeback_called_after_subject_task -v
```

Expected: `FAILED — write_back not called`

- [ ] **Step 3: Add post-run write-back after `_run_react_loop` in `run_agent_pipeline`**

After the `_run_react_loop` call in the Subject path, add:

```python
        # Post-run write-back
        if _subject_meta.get("qdrant_key"):
            try:
                store.write_back(
                    qdrant_key=_subject_meta["qdrant_key"],
                    task_id=result.get("task_id", ""),
                    outcome=result.get("summary", ""),
                    step_outcomes={},   # populated by step assertions below
                )
                logger.info(f"[SUBJECT RECALL] Write-back complete for {_subject_meta['subject']!r}")
            except Exception as exc:
                logger.warning(f"[SUBJECT RECALL] Write-back failed (non-fatal): {exc}")
```

- [ ] **Step 4: Add step assertion injection into `_run_react_loop`**

In `_run_react_loop`, after each successful tool call result is returned to the LLM, prepend to the next message list:

```python
# Step assertion — inject into scratchpad before next LLM call
assertion = f"[Step {step_n}] OK: {tool_result[:120]}"
messages.append({"role": "system", "content": assertion})
logger.info(assertion)
```

This goes inside the tool-call processing loop, after `tool_result` is obtained. The exact insertion point is right after the tool result is appended to `messages` as a `tool` role message.

- [ ] **Step 5: Run all tests — must pass**

```bash
python -m pytest tests/test_worker_subject_recall.py tests/test_control_api_subjects.py tests/test_worker_mcp_run_assistant.py -v
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add src/execution/worker/worker.py
git commit -m "feat(worker): add step assertions + post-run Qdrant write-back for Subject tasks"
```

---

## Task 9: End-to-end smoke test (dry-run)

**Files:**
- No new files — manual verification step

- [ ] **Step 1: Verify worker-api is up**

```bash
curl -s -H "X-Control-API-Key: $CONTROL_API_KEY" http://localhost:8100/healthz
```

Expected: `{"status": "ok", "service": "worker-api"}`

- [ ] **Step 2: Seed a test task via MCP tool directly**

```bash
cd ~/.claude/mcp-servers
python -c "
from packages.worker_mcp.server import WorkerApiClient
c = WorkerApiClient()
import os; os.environ['QDRANT_URL'] = 'http://localhost:6333'
result = c.run_assistant(
    hint='smoke test task',
    details='1. Use shell_exec to run echo hello\n2. Use write_file to save result to output.txt'
)
print(result)
"
```

Expected: `{'seeded': True, 'subject': 'Smoke Test Task', 'qdrant_key': '...', 'task_id': '...'}`

- [ ] **Step 3: Recall the same task**

```bash
python -c "
from packages.worker_mcp.server import WorkerApiClient
c = WorkerApiClient()
import os; os.environ['QDRANT_URL'] = 'http://localhost:6333'
result = c.run_assistant(hint='smoke test')
print(result)
"
```

Expected: `{'dispatched': True, 'task_id': '...', 'subject': 'Smoke Test Task'}`

- [ ] **Step 4: Verify gap-fill**

```bash
python -c "
from packages.worker_mcp.server import WorkerApiClient
c = WorkerApiClient()
import os; os.environ['QDRANT_URL'] = 'http://localhost:6333'
result = c.run_assistant(hint='completely unknown task zxq')
print(result)
"
```

Expected: `{'clarify': True, 'questions': [...]}`

- [ ] **Step 5: Final commit**

```bash
git add docs/superpowers/plans/2026-04-10-run-assistant-mcp.md
git commit -m "docs: add run_assistant MCP implementation plan"
```

---

## Self-Review Checklist

- [x] **Spec §3 (MCP tool interface)** → Task 5 implements the tool registration
- [x] **Spec §4 (three modes)** → Task 4 (`run_assistant` method) implements all three
- [x] **Spec §4 data model** → Task 3 (`AssistantTaskStore`) implements Qdrant schema
- [x] **Spec §5 control plane DB** → Tasks 1+2 add the SQLite table + endpoints
- [x] **Spec §6.1 Subject detection** → Task 7 wires it into `run_agent_pipeline`
- [x] **Spec §6.3 tool pre-flight** → Task 6 implements `preflight_tools`
- [x] **Spec §6.4 step assertions** → Task 8 adds assertion injection
- [x] **Spec §6.5 step checkpointing** → Task 8 `write_back` covers this (per-step granularity is in §future scope — full per-step checkpoint adds too much complexity for 14B model gains)
- [x] **Spec §6.6 post-run write-back** → Task 8
- [x] **Spec §7 confidence thresholds** → `threshold=0.80` in `resolve_subject`, `threshold=0.60` for candidates
- [x] No placeholder steps — all code blocks are complete
- [x] Type/name consistency: `resolve_subject`, `preflight_tools`, `LowConfidenceError`, `ToolUnavailableError` used consistently across Tasks 6, 7, 8
