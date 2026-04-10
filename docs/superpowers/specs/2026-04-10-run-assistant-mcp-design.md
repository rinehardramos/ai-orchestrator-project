# Design: `run_assistant` MCP Tool with Seeded Task Memory

**Date:** 2026-04-10  
**Status:** Approved  
**Scope:** `worker_mcp` (MCP tool layer) + execution worker (Gemma 14B side) + control plane DB migration

---

## 1. Problem Statement

The system has an existing `src/genesis/run_assistant.py` script that reads the `AGENT INSTRUCTIONS.md` Obsidian note from Qdrant and dispatches a task via Temporal. This approach has two weaknesses:

1. It always re-reads the same static note — no memory of what the agent actually did on prior runs.
2. Claude has to provide fully verbose instructions every time, which is expensive for a local 14B model.

**Goal:** Claude sends a short hint (e.g., `"EOS report"`). The system recovers full task context from Qdrant, fills dynamic parameters (date, config values), and dispatches a minimal but complete prompt to the worker — with enough grounding that Gemma 14B executes without hallucinating.

---

## 2. Architecture

```
Claude (Genesis)
  │
  └─► worker_mcp  ── run_assistant(hint, details?)
        │
        ├─[Mode: Recall]─► GET /tasks/subjects?q=<hint>
        │                     └─► Subject found → dispatch_task("Subject: <subject>")
        │
        ├─[Mode: Seed]───► structure steps → write Qdrant → POST /tasks/subjects
        │                     └─► dispatch_task(full structured steps)
        │
        └─[Mode: Gap-fill]► return questionnaire to Claude (no dispatch)

                                       ▼
                              Control Plane Worker API
                              POST /tasks → Temporal queue

                                       ▼
                              Execution Worker (Gemma 14B)
                              1. Parse "Subject: <X>" from task_description
                              2. Semantic search Qdrant → retrieve steps + context
                              3. Pre-flight: verify all required tools
                              4. Execute step-by-step with assertions
                              5. Checkpoint each step outcome in Qdrant
                              6. Post-run: diff outcome, write back to Qdrant
                              7. Return summary → MCP polls → Claude surfaces result
```

---

## 3. Three Operating Modes

### Mode 1 — Recall (prior run exists)

**Trigger:** `run_assistant(hint="EOS report")` with no `details`, and a matching subject exists in the control plane DB.

**Flow:**
1. MCP calls `GET /tasks/subjects?q=EOS report` on the control plane worker-api.
2. Control plane returns the canonical `Subject` string (e.g., `"EOS Report Gmail Draft"`).
3. If the similarity score of the best match is ≥ 0.80, MCP calls `dispatch_task(specialization="assistant", task_description="Subject: EOS Report Gmail Draft")`.
4. If multiple subjects match with similar scores, MCP returns a disambiguation list to Claude instead of dispatching.
5. For tasks with destructive side effects (email send, file write), MCP returns a dry-run preview first:  
   `"Will draft email to X, subject 'EOS Report - 2026-04-10', from Y. Proceed?"`
6. On user confirmation, dispatch proceeds. MCP polls `get_task_status` and surfaces the final outcome summary to Claude.

### Mode 2 — Seed (first run, full details provided)

**Trigger:** `run_assistant(hint="EOS report", details="1. Find EOS Report in Qdrant ...")` with no existing match.

**Flow:**
1. MCP parses `details` into a structured step list (see §4 Data Model).
2. Subject is normalized: strip dynamic parts (dates, IDs), lowercase, produce a stable key (e.g., `"eos report gmail draft"`).
3. Steps are written to Qdrant `assistant_tasks` collection with `required_tools` inferred from action types.
4. Subject + Qdrant key are registered in control plane: `POST /tasks/subjects`.
5. Task is dispatched immediately using the full structured steps as `task_description`.
6. After the run completes, the worker writes `last_outcome` and `step_outcomes` back to the Qdrant entry.

### Mode 3 — Gap-fill (no prior run, insufficient detail)

**Trigger:** `run_assistant(hint="EOS report")` with no `details` and no Qdrant match.

**Flow:**
1. MCP returns a structured questionnaire to Claude (no dispatch):

```json
{
  "clarify": true,
  "questions": [
    "What Qdrant note or data source should the agent read?",
    "What action should be taken? (e.g., email draft, file write, notification)",
    "Who are the recipients / targets?",
    "What should the subject / title be?",
    "Any additional parameters? (sender, format, attachments)"
  ]
}
```

2. Claude presents the questions to the user, collects answers, and re-calls `run_assistant` with `details` populated from the answers — transitioning to Mode 2.

---

## 4. Data Model

### Qdrant Collection: `assistant_tasks`

Each document represents one saved task definition. Embedding is computed from `subject + step descriptions` for semantic retrieval.

```json
{
  "subject": "EOS Report Gmail Draft",
  "subject_normalized": "eos report gmail draft",
  "steps": [
    {
      "n": 1,
      "action": "qdrant_recall",
      "params": { "note": "EOS Report" }
    },
    {
      "n": 2,
      "action": "compose_email",
      "params": { "body_source": "{step:1.content}" }
    },
    {
      "n": 3,
      "action": "gmail_draft",
      "params": {
        "to":      "{config:eos_recipient}",
        "from":    "{config:sender}",
        "subject": "EOS Report - {today}",
        "draft_to": "{config:draft_recipient}"
      }
    }
  ],
  "required_tools": ["qdrant_recall", "gmail_draft"],
  "last_run_id":    "abc-123",
  "last_outcome":   "Draft created successfully. Subject: EOS Report - 2026-04-09.",
  "step_outcomes": {
    "1": "Retrieved EOS Report, 1240 chars",
    "2": "Email body composed",
    "3": "Draft sent"
  },
  "version": 2,
  "created_at": "2026-04-10T00:00:00Z",
  "updated_at": "2026-04-10T00:00:00Z"
}
```

**Parameter syntax:**
- `{today}` — filled by MCP at dispatch time with ISO date.
- `{config:key}` — resolved from `assistant_config` Qdrant collection or env vars. Sensitive values (email addresses) live here, never inline in steps.
- `{step:N.field}` — resolved by the worker at runtime from the output of step N.

### Control Plane DB Table: `task_subjects`

```sql
CREATE TABLE task_subjects (
  subject         TEXT PRIMARY KEY,       -- canonical normalized subject
  qdrant_key      UUID NOT NULL,          -- Qdrant point ID
  last_task_id    TEXT,                   -- last Temporal workflow ID
  last_run_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX task_subjects_subject_trgm ON task_subjects
  USING gin (subject gin_trgm_ops);       -- fast fuzzy subject lookup
```

---

## 5. MCP Tool Interface

**Location:** `~/.claude/mcp-servers/packages/worker_mcp/server.py`

**New tool:**

```python
Tool(
    name="run_assistant",
    description=(
        "Trigger the assistant worker for a named task. On first run provide full "
        "step-by-step details to seed the task. On subsequent runs only a short hint "
        "is needed — the system recalls prior context from Qdrant."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "hint": {
                "type": "string",
                "description": "Short phrase identifying the task, e.g. 'EOS report'"
            },
            "details": {
                "type": "string",
                "description": (
                    "Full step-by-step instructions for first-time seeding. "
                    "Omit on recall runs."
                )
            }
        },
        "required": ["hint"]
    }
)
```

**Response envelope (returned to Claude):**

| Scenario | Shape |
|---|---|
| Recall dispatched | `{ "dispatched": true, "task_id": "...", "subject": "..." }` |
| Seed + dispatched | `{ "seeded": true, "subject": "...", "task_id": "..." }` |
| Gap-fill needed | `{ "clarify": true, "questions": [...] }` |
| Disambiguation | `{ "confirm_subject": true, "candidates": [{"subject":"...","score":0.82}, ...] }` |
| Dry-run preview | `{ "preview": true, "summary": "Will draft email to X, subject Y, from Z. Proceed?" }` |
| Task outcome | `{ "status": "completed", "summary": "...", "cost_usd": 0.00 }` |

---

## 6. Worker Changes

**Entry point:** `src/execution/worker/worker.py` — thin pre-processing before the existing `run_agent_pipeline`.

### 6.1 Subject Detection

If `task_description` starts with `"Subject: "`, activate the Subject recall path:

```python
if task_payload["description"].startswith("Subject: "):
    subject = task_payload["description"].removeprefix("Subject: ").strip()
    task_payload = await resolve_subject(subject, task_payload)
```

### 6.2 `resolve_subject(subject)` — new helper

1. Semantic search `assistant_tasks` Qdrant collection using `subject` as query text.
2. If top hit score < 0.80: raise `LowConfidenceError(subject, score, best_match)` — propagates back as worker error to MCP.
3. Resolve parameterized fields: `{today}` → date, `{config:X}` → config lookup, producing a fully-resolved step list.
4. Infer `required_tools` by mapping action names to registered tool names (e.g., `"gmail_draft"` → `gmail_draft`, `"qdrant_recall"` → `qdrant_recall`).
5. Reconstruct `task_description` as a numbered step prompt for the ReAct loop.

### 6.3 Tool Pre-flight

Before entering ReAct loop:
```python
missing = [t for t in required_tools if t not in TOOL_REGISTRY_NAMES]
if missing:
    raise ToolUnavailableError(missing)
```
Fails fast with a clear error — no hallucinated success.

### 6.4 Step Assertions

After each tool call, the worker injects one grounded fact line into the ReAct scratchpad (as a `system` message before the next agent turn — not printed to stdout):
```
[Step 1] OK: retrieved EOS Report note, 1240 chars, last modified 2026-04-09
[Step 2] OK: email body composed, 380 chars
[Step 3] OK: Gmail draft created
```
Injecting into the scratchpad rather than the task description keeps the initial prompt short while anchoring the model's next planning step against verified facts.

### 6.5 Step Checkpointing

After each successful step, write to Qdrant:
```python
qdrant_client.update_payload(
    collection_name="assistant_tasks",
    point_id=qdrant_key,
    payload={"step_outcomes": {str(step_n): assertion_text}}
)
```
Enables resume-from-step on next run if the task fails mid-way.

### 6.6 Post-run Write-back

On task completion:
1. Compute outcome summary (from `final_summary`).
2. Diff against `last_outcome` using cosine similarity — flag if < 0.70 (significant drift).
3. Write back: `last_outcome`, `step_outcomes`, `last_run_id`, `version += 1`, `updated_at`.

---

## 7. Confidence & Safety Thresholds

| Check | Threshold | Action on fail |
|---|---|---|
| Qdrant subject match | cosine ≥ 0.80 | Return `low_confidence_match` to Claude |
| Multi-subject disambiguation | top-2 scores within 0.05 | Return candidate list to Claude |
| Post-run outcome drift | cosine ≥ 0.70 | Flag drift notice to Claude (non-blocking) |
| Destructive action dry-run | any email/write action | Preview + confirm before dispatch |

---

## 8. What Does NOT Change

- `run_agent_pipeline` core ReAct loop — no modifications.
- `multi_agent_graph.py` — untouched.
- `src/genesis/run_assistant.py` — kept as-is for direct Temporal path (legacy/fallback).
- Existing `dispatch_task`, `get_task_status`, `list_workers` MCP tools — unchanged.

---

## 9. Files Affected

| File | Change |
|---|---|
| `~/.claude/mcp-servers/packages/worker_mcp/server.py` | Add `run_assistant` tool + `WorkerApiClient.run_assistant()` + inline Qdrant helpers for `assistant_tasks` |
| `src/mercenary/api/app/api/` | Add `GET /tasks/subjects` + `POST /tasks/subjects` endpoints |
| `src/mercenary/api/app/db/` | Add `task_subjects` table migration |
| `src/execution/worker/worker.py` | Add Subject detection + `resolve_subject()` helper |
| `src/execution/worker/tools.py` | Ensure `qdrant_recall` tool is registered |

---

## 10. Open Questions (resolved)

- **Sensitive values (emails):** Stored in `assistant_config` Qdrant collection or env vars, referenced by `{config:key}` in steps. Never in Claude's context.
- **First-run fallback:** No fallback to `AGENT INSTRUCTIONS.md` — first run requires either `details` or gap-fill dialog.
- **Local model (Gemma 14B):** Step assertions (#6.4) and tool pre-flight (#6.3) are the primary hallucination mitigations chosen for this model class.
