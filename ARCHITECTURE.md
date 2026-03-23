# AI Orchestration System — Architecture

This document describes the current architecture of the AI Orchestration system across its three planes: the **Genesis Node**, the **Control Plane**, and the **Execution Plane**.

---

## System Topology

```mermaid
graph TD
    %% ═══════════════════════════════════════════
    %% GENESIS NODE (Local Machine)
    %% ═══════════════════════════════════════════
    subgraph GN["Genesis Node (Local CNC)"]
        direction TB
        CLI["CLI\nsrc/genesis/cli.py"]
        TGM["Telegram Monitor\nsrc/genesis/orchestrator/telegram_monitor.py"]
        SCH["TaskScheduler\nsrc/genesis/orchestrator/scheduler.py"]
        ANA["TaskAnalyzer\nsrc/genesis/analyzer/task_analyzer.py"]
        NOT["TelegramNotifier"]
        SQLite[("Offline Queue\nSQLite")]

        CLI --> SCH
        TGM --> SCH
        SCH --> ANA
        SCH --> NOT
        SCH --> SQLite
    end

    %% ═══════════════════════════════════════════
    %% CONTROL PLANE (192.168.100.249)
    %% ═══════════════════════════════════════════
    subgraph CP["Control Plane (Remote Central Node — 192.168.100.249)"]
        direction TB

        subgraph WF["Workflow Engine"]
            TMP["Temporal Server\n:7233 gRPC"]
            TMPUI["Temporal UI\n:8233"]
            PG[("PostgreSQL\n:5432")]
            TMP --- PG
        end

        subgraph DS["Control Services"]
            DISP["Dispatcher\n:8001"]
            SEL["Model Selector\n:8002"]
            COORD["Coordinator\n(heartbeat)"]
        end

        subgraph MEM["Memory & Cache"]
            QD[("Qdrant\n:6333\nVector DB")]
            RD[("Redis\n:6379\nL1 Cache")]
        end

        subgraph OBS["Observability Stack"]
            OPIK_BE["Opik Backend\n:8080"]
            OPIK_FE["Opik UI\n:5173"]
            MYSQL[("MySQL")]
            CH[("ClickHouse")]
            MINIO[("MinIO")]
            OPIK_BE --- MYSQL
            OPIK_BE --- CH
            OPIK_BE --- MINIO
            OPIK_FE --> OPIK_BE
        end
    end

    %% ═══════════════════════════════════════════
    %% EXECUTION PLANE (Worker Node)
    %% ═══════════════════════════════════════════
    subgraph EP["Execution Plane (Worker — 192.168.100.249 / .100)"]
        direction TB

        subgraph WRK["ai-worker (Docker)"]
            direction TB
            TW["Temporal Worker\nAIOrchestrationWorkflow"]
            MAG["Multi-Agent Graph\nmulti_agent_graph.py"]
            AGT["Single-Agent ReAct Loop\nworker.py"]
            MR["ModelRouter\nmodel_router.py"]
            TOOLS["Tools\nshell_exec · read/write_file\ngit · search_web · memory"]
            SBX["Sandbox\nworkspace isolation\ncommand blocklist"]

            TW --> MAG
            MAG --> AGT
            AGT --> MR
            AGT --> TOOLS
            TOOLS --> SBX
        end

        subgraph LLM_OUT["LLM Providers"]
            OR["OpenRouter\ncloud models"]
            GG["Google Gemini\nnative SDK"]
            LMS["LMStudio / Ollama\n:1234 local"]
        end

        MR --> OR
        MR --> GG
        MR --> LMS
    end

    %% ═══════════════════════════════════════════
    %% CROSS-PLANE CONNECTIONS
    %% ═══════════════════════════════════════════
    SCH -- "1 pre-flight semantic search" --> QD
    SCH -- "2 submit workflow" --> TMP
    TMP -- "3 poll task" --> TW
    AGT -- "4 vector search / store insight" --> QD
    AGT -- "5 L1 state cache" --> RD
    AGT -- "6 LLM traces" --> OPIK_BE
    TW -- "7 complete workflow" --> TMP
    TMP -- "8 return result" --> SCH
    SCH -- "9 notify" --> NOT
    COORD -. "heartbeat" .-> TW
```

---

## Multi-Agent Orchestration

When a task arrives at the worker, the **Multi-Agent Graph** decomposes it and routes execution through a dependency-aware pipeline.

```mermaid
flowchart TD
    IN["Task arrives via\nTemporal activity"] --> PL

    subgraph MAG["Multi-Agent Graph (LangGraph StateGraph)"]
        PL["Planner Node\nLLM → ExecutionPlan\n{ strategy, subtasks[] }"]

        PL --> RT{"orchestrator_router"}

        RT -- "strategy: single_agent" --> W0["SubTask Worker\n(main_task)"]

        RT -- "strategy: parallel_isolated\ndeps met simultaneously" --> W1["SubTask Worker 1\n(specialization A)"]
        RT -- "strategy: parallel_isolated" --> W2["SubTask Worker 2\n(specialization B)"]
        RT -- "strategy: parallel_isolated" --> WN["SubTask Worker N\n(specialization ...)"]

        RT -- "strategy: coordinated_team\nwave 1 (no deps)" --> WA["SubTask Worker A\n(e.g. research)"]
        WA -- "result → shared_artifacts" --> RT2{"orchestrator_router\n(re-evaluated)"}
        RT2 -- "wave 2 (deps met,\nupstream context injected)" --> WB["SubTask Worker B\n(e.g. copywriting)\n+ context from A"]

        W0 --> SYN["Synthesis Node\naggregate results"]
        W1 --> SYN
        W2 --> SYN
        WN --> SYN
        WB --> SYN
    end

    subgraph SW["Each SubTask Worker"]
        SAP["Single-Agent ReAct Pipeline\n(run_agent_pipeline)"]
        SAP --> LLM2["ModelRouter\n→ LLM call"]
        SAP --> TC["Tool Executor\nshell · file · git · web · memory"]
        LLM2 --> SAP
        TC --> SAP
        SAP -- "task_complete()" --> SUM["Summary + Cost"]
    end

    SYN --> OUT["Final result\nreturned to Temporal"]
    W0 -.-> SAP
    WA -.-> SAP
    WB -.-> SAP
```

---

## Model Router Fallback Chain

Every LLM call in the system goes through `ModelRouter.call_llm()`, which applies a transparent 3-step fallback when configured models fail.

```mermaid
flowchart LR
    IN["call_llm(task_type, specialization)"] --> RES["Resolve from profiles.yaml\nmodel + provider"]
    RES --> A1

    subgraph CHAIN["Fallback Chain (transparent to callers)"]
        A1["Attempt 1\nConfigured provider + model"]
        A1 -- "401 Unauthorized\n402 Insufficient credits" --> HARD["Re-raise\n(no fallback)"]
        A1 -- "local provider\nunavailable" --> A2
        A1 -- "invalid model name\n400 / 404" --> A3

        A2["Attempt 2\nSame model → OpenRouter"]
        A2 -- "model also invalid\non OpenRouter" --> A3
        A2 -- "401 / 402" --> HARD

        A3["Attempt 3\nSAFE_FALLBACK_MODEL\ngoogle/gemini-2.0-flash-001\non OpenRouter"]
    end

    subgraph PROVIDERS["Provider Dispatch"]
        P1["provider: openrouter\n→ _call_remote()"]
        P2["provider: google\n→ _call_google()\nnative genai SDK"]
        P3["provider: lmstudio / ollama\n→ _call_local()\n:1234"]
    end

    RES -- "openrouter" --> P1
    RES -- "google" --> P2
    RES -- "lmstudio / ollama" --> P3
    P2 -- "client unavailable" --> P1
```

---

## Tiered Memory Architecture

All planes share a three-tier memory system. Reads and writes flow through the `HybridMemoryStore` and `KnowledgeBaseClient`.

```mermaid
flowchart LR
    subgraph L1["L1 — Ephemeral (Redis :6379)"]
        RC["TTL-based cache\nLangGraph checkpointing\nTask metadata (SETEX)"]
    end

    subgraph L2["L2 — Persistent Semantic (Qdrant :6333)"]
        QC["agent_insights_v4\nVectors: nomic-embed-code\n3584 dims\n\nStores: past fixes,\nresolved bugs,\narchitectural insights"]
    end

    subgraph L3["L3 — Cold Archive (S3)"]
        S3["Task execution logs\nAudit trails\nLong-term storage"]
    end

    GEN["Genesis Node\nPre-flight check"] -- "semantic search\nbefore task submit" --> L2
    WKR["Worker\nContext injection"] -- "query top-3 insights\nbefore agent loop" --> L2
    WKR -- "store insight\nafter task completes" --> L2
    WKR -- "ephemeral state\nReAct loop cache" --> L1
    WKR -- "archive on\ntask completion" --> L3
    L1 -. "evicts after TTL" .-> L2
```

---

## Request Lifecycle

```mermaid
sequenceDiagram
    actor User
    participant CLI as Genesis CLI
    participant SCH as Scheduler
    participant QD as Qdrant (L2)
    participant TMP as Temporal
    participant WRK as Worker
    participant LLM as ModelRouter / LLM
    participant OPIK as Opik

    User->>CLI: Submit task
    CLI->>SCH: schedule(task)
    SCH->>QD: semantic_search(task) — pre-flight
    QD-->>SCH: similar past warnings
    SCH-->>CLI: display warnings (if any)
    SCH->>TMP: start_workflow(task)

    TMP->>WRK: dispatch activity
    WRK->>QD: fetch context (top-3 insights)
    QD-->>WRK: relevant past insights

    loop ReAct Loop
        WRK->>LLM: call_llm(messages, tools)
        LLM-->>OPIK: trace span
        LLM-->>WRK: response / tool_calls
        WRK->>WRK: execute tools
    end

    WRK->>QD: store_insight(result)
    WRK->>TMP: complete_activity(result)
    TMP-->>SCH: workflow result
    SCH-->>CLI: display result
    SCH-->>User: Telegram notification
```

---

## Component Reference

| Component | Location | Port | Role |
|---|---|---|---|
| CLI | `src/genesis/cli.py` | — | User-facing task submission |
| Telegram Monitor | `src/genesis/orchestrator/telegram_monitor.py` | — | Headless task intake |
| TaskScheduler | `src/genesis/orchestrator/scheduler.py` | — | Pre-flight + Temporal client |
| TaskAnalyzer | `src/genesis/analyzer/task_analyzer.py` | — | Task type detection |
| Temporal Server | Control Plane | 7233 (gRPC) | Workflow lifecycle |
| Temporal UI | Control Plane | 8233 | Workflow visibility |
| PostgreSQL | Control Plane | 5432 | Temporal state store |
| Qdrant | Control Plane | 6333 (HTTP) | L2 vector memory |
| Redis | Control Plane | 6379 | L1 ephemeral cache |
| Opik Backend | Control Plane | 8080 (HTTP) | LLM trace ingestion |
| Opik Frontend | Control Plane | 5173 | Trace visualization UI |
| Dispatcher | `src/control/dispatcher/dispatcher.py` | 8001 | Task-type routing |
| Model Selector | `src/control/model_selector/selector.py` | 8002 | Model capability matching |
| Coordinator | `src/control/coordinator/coordinator.py` | — | Worker heartbeat aggregation |
| ai-worker | `src/execution/worker/worker.py` | — | Temporal worker + ReAct agent |
| Multi-Agent Graph | `src/execution/worker/multi_agent_graph.py` | — | LangGraph planner + workers |
| ModelRouter | `src/execution/worker/model_router.py` | — | LLM dispatch + fallback chain |
| Tools | `src/execution/worker/tools.py` | — | Agent toolset (15+ tools) |
| Sandbox | `src/execution/worker/sandbox.py` | — | Workspace isolation + blocklist |
| HybridMemoryStore | `src/shared/memory/hybrid_store.py` | — | L1/L2/L3 unified interface |
| KnowledgeBaseClient | `src/shared/memory/knowledge_base.py` | — | Semantic search + embedding |
