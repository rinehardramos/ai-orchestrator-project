# Architecture Assessment & Optimization Recommendations

**Task ID:** `ts-eval-00923`
**Node:** Genesis/CNC (Raspberry Pi L0) -> Executed on: Central Dev Node (Worker)
**Objective:** Assess current AI orchestration system, recommend optimizations for a tiered memory architecture, and integrate Temporal/Langgraph for agentic operations.

---

## 1. Current State Assessment
- **Raspberry Pi as CNC:** The Pi is acting as an active orchestrator but risks bottlenecking if it attempts to execute memory-intensive or long-running worker tasks locally.
- **Worker Management:** Currently reliant on manual or lightweight synchronous execution models (Python loops / simple SQS triggers). This lacks retryability, replayability, and state-resurrection if the worker fails mid-reasoning.
- **Memory Management:** Memory is currently monolithic or non-existent (relying strictly on context windows or basic SQLite).

## 2. Recommended Optimizations & "Genesis Node" Architecture

### A. The "Thin" Genesis Node (Raspberry Pi)
The Raspberry Pi must act strictly as an **L0 Gateway** (Control Node).
- **Responsibilities:**
  1. Parse natural language intent via `gemini-3.1-flash-lite`.
  2. Map intent to infrastructure plans via `Analyzer Agent`.
  3. Emit infrastructure provisioning commands to a remote Central Node (using Pulumi Automation API or SSH/Docker contexts).
  4. Submit workflows to Temporal (which lives on the Central Node).
- **Constraints:** *Never* run vector databases (Qdrant), model inference (unless tiny local models), or heavy state machines directly on the Pi.

### B. The Heavy Central Node (Dev Environment / AWS EC2)
The central node will house the actual execution environment. It should be provisioned dynamically and run a full Dockerized stack (see `src/control/docker-compose.core.yml`):
- **Temporal Server:** For distributed workflow orchestration, handling timeouts, and resurrecting agent states if a pod crashes.
- **Langgraph Workers:** Running the actual cyclical reasoning graphs. Each step in the Langgraph should ideally be wrapped in a Temporal Activity to ensure the graph's execution state is durable.
- **Tiered Memory Services:** Redis (L1) and Qdrant (L2) containers.

### C. Tiered Memory Architecture
To support continuous, context-aware agentic operations across ephemeral workers:

*   **L0: LLM Context Window (Ultra-Fast, High Cost):** Transient state passed directly in API calls to Gemini/Claude.
*   **L1: Redis (Fast, Ephemeral State):** Used for caching recent conversations, Langgraph checkpointing, and passing large temporary objects between Temporal activities without bloating Temporal history.
*   **L2: Qdrant (Persistent, Semantic Vector Search):** Long-term memory for past reasoning outputs, RAG document retrieval, and learned "agent behaviors."
*   **L3: S3/Postgres (Cold, Archival):** Complete audit trails, logging, and raw task data.

### D. Langgraph + Temporal Integration Strategy
1. **Temporal Workflow:** Acts as the outer wrapper. It manages the lifecycle of the entire agentic task, ensuring the process is executed reliably, retried on API failures, and can wait for external signals (e.g., human-in-the-loop approvals).
2. **Langgraph State Machine:** Acts as the inner cognitive loop. Inside a Temporal Activity, the Langgraph engine iterates over agent steps (Plan -> Act -> Validate) using its built-in cyclical state.
3. **Checkpointing:** Configure Langgraph to use the `redis` container as its `checkpointer`. If the worker crashes, the Temporal Workflow restarts the Langgraph activity, which seamlessly resumes from the exact L1 Redis checkpoint.

---
**Conclusion:** 
By offloading all Docker containers and workflow states to the Central Node and utilizing Temporal for fault tolerance combined with Langgraph for reasoning loops, the Raspberry Pi remains highly responsive as a pure Command & Control (CNC) genesis interface.
