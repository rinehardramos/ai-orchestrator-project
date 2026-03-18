# Architectural Mandate

This system uses a three-plane architecture. You are currently operating on the **Genesis Node (CNC)**.

**CRITICAL RULES:**
1. **CNC Node (Local):** This machine is NOT a worker node. Its role is task delegation and infrastructure provisioning. Do not run any application execution, shell execution, or verification tasks directly on this machine except for performing code changes to the repository.
2. **Worker Node (Remote):** All jobs (e.g., executing terraform, pulumi, cdk, or application code) MUST be sent to the remote worker node via the Temporal queue.
3. **Task Delegation:** Use the Temporal scheduler (`src/orchestrator/scheduler.py`) to delegate tasks.

## System Topology

```mermaid
graph TD
    subgraph "Genesis Node (CNC) - YOU ARE HERE"
        CLI[src/cli.py] --> Scheduler[src/orchestrator/scheduler.py]
        Scheduler --> KB_Client_CNC[src/memory/knowledge_base.py]
    end

    subgraph "Control Plane (Remote Central Node)"
        Temporal[Temporal Server]
        Qdrant[Qdrant Vector DB]
        Redis[Redis Cache]
        Postgres[Postgres - Temporal DB]
    end

    subgraph "Execution Plane (Remote Worker Container)"
        Worker[central_node/worker.py]
        KB_Client_Worker[src/memory/knowledge_base.py]
        Jobs_Config[config/jobs.yaml]
    end

    %% Initialization & Pre-flight Flow
    CLI -- 1. Submit Task --> Scheduler
    Scheduler -- 2. Semantic Search --> Qdrant
    Qdrant -- 3. Relevant Warnings --> Scheduler
    Scheduler -- 4. Signal Warning to CLI --> CLI
    Scheduler -- 5. Push Task --> Temporal

    %% Execution Flow
    Temporal -- 6. Poll Task --> Worker
    Worker -- 7. Semantic Search --> Qdrant
    Worker -- 8. Load Dynamic Logic --> Jobs_Config
    Worker -- 9. Execute Shell/Langgraph --> Result[Subprocess / LLM]
    Result -- 10. Complete Workflow --> Temporal
    Temporal -- 11. Return Final Result --> Scheduler
    Scheduler -- 12. Display to User --> CLI
```