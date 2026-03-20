# AI Orchestration Project - Architecture

This document describes the three-plane architecture of the AI Orchestration system: the **Genesis Node** (CNC), the **Control Plane**, and the **Execution Plane**.

## 🏗️ System Topology

```mermaid
graph TD
    subgraph "Genesis Node (CNC)"
        Main[src/cnc/main.py]
        CLI[src/cnc/cli.py] --> Scheduler[src/cnc/orchestrator/scheduler.py]
        Scheduler --> KB_Client_CNC[src/shared/memory/knowledge_base.py]
        Scheduler --> OfflineDB[(Offline SQLite DB)]
        Scheduler --> Notifier[Telegram Notifier]
        Backup[src/cnc/orchestrator/backup_manager.py] --> SystemBackups[(Local Backups)]
    end

    subgraph "Control Plane (Remote Central Node)"
        Temporal[Temporal Server]
        Qdrant[Qdrant Vector DB]
        Redis[Redis Cache]
        Postgres[Postgres - Temporal DB]
        LiteLLM[LiteLLM Proxy]
        Dispatcher[src/control/dispatcher/dispatcher.py]
        Catalog[src/control/catalog/catalog.py]
        DAG_Service[src/control/dag/dag_service.py]
        Model_Selector[src/control/model_selector/selector.py]
        Scaler[src/control/scaler/scaler.py]
        Coordinator[src/control/coordinator/coordinator.py]
    end

    subgraph "Execution Plane (Remote Worker Container)"
        Worker[src/execution/worker/worker.py]
        KB_Client_Worker[src/shared/memory/knowledge_base.py]
        Jobs_Config[config/jobs.yaml]
    end

    %% Initialization & Pre-flight Flow
    CLI -- 1. Submit Task --> Scheduler
    Scheduler -- 2. Semantic Search (with LRU Cache) --> Qdrant
    Qdrant -- 3. Relevant Warnings --> Scheduler
    Scheduler -- 4. Interactive Warning to CLI --> CLI
    Scheduler -- 5. Push Task (or Queue Offline) --> Temporal
    Scheduler -- Alerts --> Notifier

    %% Execution Flow
    Temporal -- 6. Poll Task --> Worker
    Worker -- 7. Semantic Search --> Qdrant
    Worker -- 8. Load Dynamic Logic --> Jobs_Config
    Worker -- 9. Execute Shell --> Result[Subprocess]
    Worker -- 9a. Unified AI Call --> LiteLLM
    LiteLLM -- 9b. Model Response --> Worker
    Result -- 10. Complete Workflow --> Temporal
    Worker -- 10. Complete Workflow --> Temporal
    Temporal -- 11. Return Final Result --> Scheduler
    Scheduler -- 12. Display to User & Notify --> CLI
    
    %% Backup Flow
    Backup -. Scheduled Snapshot .-> Qdrant
    Backup -. Scheduled Backup .-> Postgres
```

## 🛠️ Components Description

### 1. Genesis Node (CNC)
*   **Role:** Task Orchestration & Human-in-the-Loop.
*   **Key Action:** Performs the **Pre-flight Check**. Before sending any task to the remote workers, it queries the Knowledge Base (Qdrant) with an LRU cache to identify historical failures. It intercepts the flow to interactively warn the operator.
*   **Offline Resilience:** Uses a local SQLite database (`offline_queue.db`) to queue tasks when the Central Node is unreachable.
*   **Notifications:** Uses `TelegramNotifier` to push real-time status updates (submitted, offline, complete, failed).
*   **Data Safety:** The `BackupManager` orchestrates snapshots of Qdrant and Temporal Postgres.

### 2. Control Plane (Central Node)
*   **Role:** State Management & Networking.
*   **Temporal:** Manages the lifecycle of long-running workflows, ensuring reliability and retries.
*   **LiteLLM:** Acts as the unified proxy/gateway for all LLM calls across the control and execution planes, abstracting provider APIs (OpenAI, Anthropic, Gemini).
*   **Qdrant:** Stores the semantic knowledge base as high-dimensional vectors (gemini-embedding-001).
*   **Redis:** Provides L1 ephemeral caching for fast context retrieval.

### 3. Execution Plane (Worker Node)
*   **Role:** High-Privilege Execution.
*   **Worker:** A containerized agent that executes tasks. It is **Data-Driven**, meaning it does not have hardcoded logic. Instead, it dynamically loads its task definitions from `config/jobs.yaml`.
*   **Execution Guardrail:** Like the CNC node, the worker performs its own internal KB lookup before starting a subprocess, ensuring that even if the CNC pre-flight is bypassed, the execution remains context-aware.
*   **Horizontal Scaling:** Multiple workers can run simultaneously — all are stateless and share the same Temporal task queue. Add machines by pointing them at the Control Plane (see `docs/cluster_expansion.md`).

---

## 🔄 Agent Feedback Loop & Cross-Agent Learning

The system implements a continuous self-improvement cycle across all agents using the shared L2 memory layer.

```mermaid
graph LR
    A[Worker Executes Task] --> B{Success or Failure?}
    B -- Success with Insight --> C[Embed MemoryEntry in Qdrant]
    B -- Failure / Bug Fixed --> C
    C --> D[L2 Qdrant — agent_insights collection]
    D --> E[All Future Agents: Pre-flight KB Query]
    E --> F[Retrieve Relevant Warnings & Fixes]
    F --> A
```

### How It Works

1. **During Execution**: Every worker queries Qdrant (`agent_insights` collection) via semantic search before starting a task. If a similar task has failed before, the warning surfaces to the CNC node's pre-flight check and can be surfaced to the user.

2. **After Resolution**: When a complex bug or architectural blocker is resolved, the resolving agent embeds a `MemoryEntry` into Qdrant using `KnowledgeBaseClient`. This entry includes:
   - The symptom / traceback
   - The root cause
   - The applied fix
   - Relevant tags for future retrieval

3. **Cross-Agent Sharing**: Because all workers point to the same Qdrant instance on the Control Plane, insights from one agent are immediately available to every other agent — including on newly added worker nodes.

4. **Semantic Retrieval**: Qdrant uses vector similarity search (not keyword matching), so a future agent encountering a *similar but not identical* problem will still retrieve the relevant historical fix.

### Reporting to the User

Agents report status back through two channels:

| Channel | When | Content |
|:--------|:-----|:--------|
| **CLI (stdout)** | Interactive sessions | Task result, warnings, pre-flight alerts |
| **Telegram Notifier** | All modes (headless-friendly) | Submitted, running, complete, failed, blocked |

The Telegram notifier (`src/cnc/orchestrator/telegram_monitor.py`) allows the system to operate fully headless on a Raspberry Pi while the user receives real-time updates on their phone.

---

## 📦 Key Configuration Files

| File | Purpose |
|:-----|:--------|
| `config/settings.yaml` | Network topology (worker IPs, SSH keys, ports) |
| `config/profiles.yaml` | LLM model definitions and infrastructure tiers |
| `config/jobs.yaml` | Data-driven task definitions for the worker |
| `config/cluster_nodes.yaml` | Ansible inventory for multi-node deployments |
