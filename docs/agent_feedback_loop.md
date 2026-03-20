# Agent Feedback Loop & Cross-Agent Knowledge Sharing

## Overview

The AI Orchestration system implements a continuous learning cycle where every agent (worker) that resolves a non-trivial problem contributes that knowledge back to the shared L2 memory layer. All future agents — on any node — benefit from this growing knowledge base before executing a task.

The shared memory lives in **Qdrant** (the Control Plane's vector database), in the `agent_insights` collection. Because all workers point to the same Qdrant instance, knowledge is automatically shared across agents without any additional synchronization.

---

## The Feedback Cycle

```
Task Submitted
      ↓
Pre-flight KB Query (Qdrant semantic search)
      ↓  [warnings surfaced if similar past failures found]
Task Executed on Worker
      ↓
Outcome: Success / Failure
      ↓
[If insight-worthy] Embed MemoryEntry → Qdrant
      ↓
Next agent encounters similar problem → retrieves this fix
```

### Step 1: Pre-flight Check (CNC Node)

Before submitting a task to the Temporal queue, the Genesis Node's scheduler (`src/cnc/orchestrator/scheduler.py`) performs a semantic search against Qdrant:

```python
results = kb_client.search("agent_insights", task_description, top_k=3)
```

If relevant past failures are found, the CNC node:
- Displays a warning to the user (interactive CLI)
- Sends a Telegram alert (headless mode)
- The user can then decide to proceed, abort, or modify the task

### Step 2: Worker-Side Guard

The remote worker (`src/execution/worker/worker.py`) performs its own KB lookup when it picks up a task from Temporal. This dual-check ensures context-awareness even if the CNC pre-flight was bypassed or the task was submitted programmatically.

### Step 3: Embedding Insights (Post-Execution)

After resolving a complex bug, architectural blocker, or non-obvious issue, the agent embeds a `MemoryEntry`:

```python
from src.shared.memory.knowledge_base import KnowledgeBaseClient, MemoryEntry

kb = KnowledgeBaseClient()
entry = MemoryEntry(
    collection="agent_insights",
    content="Resolved: temporal connection refused. Root cause: gRPC target missing port. Fix: ensure TEMPORAL_HOST_URL includes :7233",
    metadata={
        "type": "bug_fix",
        "severity": "critical",
        "tags": ["temporal", "grpc", "connection"]
    }
)
kb.upsert(entry)
```

**When to embed:**
- Complex bugs resolved (not trivial typos)
- Architectural decisions with non-obvious rationale
- Recurring failure patterns and their root causes
- Tool/environment pitfalls (e.g., Docker path issues, ARM vs amd64 binaries)

---

## Cross-Agent Knowledge Sharing

Since all workers share the same Qdrant instance on the Control Plane:

- A worker on `worker-node-01` resolves a Pulumi provisioning bug → embeds fix
- A worker on `worker-node-02` (freshly added to the cluster) encounters the same issue → retrieves the exact fix before even attempting to run

**Semantic, not keyword-based**: Qdrant uses vector similarity, so a query like "terraform module not found" will retrieve a past entry about "pulumi provider missing" if the symptom vectors are sufficiently similar.

---

## Reporting to the User

Agents communicate task status through two channels:

### 1. CLI Output (Interactive)
The CNC node's CLI displays:
- Pre-flight warnings with historical failure details
- Task submission confirmation and Temporal workflow ID
- Final result (stdout/stderr from the worker)

### 2. Telegram Notifications (Headless / Remote)
The `TelegramNotifier` (`src/cnc/orchestrator/telegram_monitor.py`) sends messages for:

| Event | Message |
|:------|:--------|
| Task submitted | "Task queued: `<task_id>` — `<description>`" |
| Task running | "Worker picked up: `<workflow_id>`" |
| Task succeeded | "Completed: `<task_id>` — `<summary>`" |
| Task failed | "Failed: `<task_id>` — `<error>`" |
| Blocked / warning | "Pre-flight warning: `<warning text>`" |
| Offline (no Control Plane) | "Task queued offline — will retry on reconnect" |

To enable Telegram notifications, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env` file.

---

## Offline Resilience

If the Control Plane is unreachable when a task is submitted:
1. The task is saved to a local SQLite database (`offline_queue.db`) on the Genesis Node.
2. The scheduler periodically retries the connection.
3. Once reconnected, the offline queue is automatically flushed to Temporal.

This ensures the feedback loop is never broken by transient network issues.

---

## See Also

- `docs/KNOWLEDGE_BASE.md` — Operational lessons and known pitfalls
- `docs/cluster_expansion.md` — Adding more worker nodes
- `ARCHITECTURE.md` — Full system topology and component descriptions
