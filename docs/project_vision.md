# Project Vision: Autonomous AI Agent Orchestration

## Mission

Build a self-improving fleet of AI agents that autonomously work on software projects, report outcomes to the user, and continuously learn from each other — with minimal human intervention.

The user delegates work. Agents execute, report, and grow smarter over time. The system runs headless on low-power hardware (Raspberry Pi) as the command node, with workers on separate machines accessible via LAN or cloud.

---

## Core Design Principles

### 1. Delegation, Not Babysitting
The user submits a task ("deploy the new API version", "fix the failing tests in repo X", "run a security audit"). From that point, the agent is responsible for:
- Understanding the task
- Checking historical knowledge for relevant warnings
- Executing the work on a remote worker node
- Reporting the outcome (success, failure, or blocker)

The user should never need to watch over an agent's shoulder.

### 2. Agents Report, Not Hide
Every agent communicates its status through structured reporting:

| Status | Meaning | User Action Required |
|:-------|:--------|:--------------------|
| **Submitted** | Task accepted and queued | None |
| **Running** | Worker picked up the task | None |
| **Succeeded** | Task completed successfully | Review output at leisure |
| **Failed** | Task failed with error details | Investigate if critical |
| **Blocked** | Agent cannot proceed without input | Respond with guidance |
| **Warning** | Pre-flight found relevant past failures | Decide to proceed or abort |

Reporting happens via two channels:
- **CLI** — for interactive sessions
- **Telegram** — for headless/remote operation (primary mode on Pi)

### 3. Workers Run Elsewhere
The Genesis Node (Raspberry Pi / CNC) never executes tasks itself. All work runs on separate machines:

- **LAN workers**: Machines on the local network (e.g., a Mac Mini, a spare server). Connected via SSH, discovered via `config/cluster_nodes.yaml`.
- **Cloud workers**: VMs provisioned on-demand via Pulumi (AWS EC2, GCP Cloud Run). Spun up when local capacity is insufficient or task requires specific infrastructure.

Workers are stateless, containerized, and horizontally scalable. Adding a new worker is as simple as pointing it at the Control Plane's Temporal and Qdrant endpoints.

---

## Autonomy Model

### What Agents Decide Alone
- **Execution strategy**: Which shell commands to run, in what order
- **Model selection**: Which LLM to use for reasoning subtasks (via LiteLLM + profiles.yaml)
- **Knowledge retrieval**: Querying Qdrant for relevant past insights before and during execution
- **Retry logic**: Transient failures are retried automatically via Temporal's durable workflows
- **Insight embedding**: After resolving a non-trivial issue, the agent autonomously stores the lesson in Qdrant

### What Requires Human Input
- **Blocker escalation**: When the agent determines it cannot proceed (missing credentials, ambiguous requirements, infrastructure unavailable), it reports a `blocked` status with context and waits
- **Pre-flight warnings**: If historical failures are found for a similar task, the user is warned and can choose to proceed or abort
- **Destructive operations**: Tasks flagged as high-risk (e.g., production deployments, data migrations) require explicit user confirmation before execution
- **Budget thresholds**: If estimated cost exceeds configured limits, the task pauses for approval

---

## Knowledge Sharing & Feedback Loop

### Per-Agent Learning
Each agent learns from its own execution history. When a complex bug is resolved or a non-obvious fix is applied, the agent embeds a `MemoryEntry` into Qdrant's `agent_insights` collection containing:
- The symptom / traceback
- The root cause analysis
- The applied fix
- Tags for future semantic retrieval

### Cross-Agent Sharing
All agents — regardless of which worker node they run on — share the same Qdrant instance on the Control Plane. This means:

1. **Agent A** on `worker-01` resolves a Docker networking issue and embeds the fix
2. **Agent B** on `worker-02` (possibly a newly added cloud VM) encounters a similar issue
3. Agent B's pre-flight query retrieves Agent A's fix via vector similarity — before even attempting execution

This creates a **semantic immune system**: the fleet gets smarter with every resolved issue, and no agent repeats a mistake that any other agent has already solved.

### Retrieval Is Semantic, Not Keyword
Qdrant uses vector similarity search. An agent searching for "terraform provider timeout" will find entries about "pulumi resource provisioning failure" if the underlying symptoms are similar. This makes the knowledge base robust to variations in phrasing and tooling.

### The Learning Cycle

```
Task Submitted
      |
      v
Pre-flight KB Query ──> [warnings found?] ──> Alert User
      |
      v
Worker Executes Task
      |
      v
Outcome: Success / Failure / Blocked
      |
      v
[If insight-worthy] ──> Embed MemoryEntry in Qdrant
      |
      v
All future agents benefit from this knowledge
```

---

## Multi-Project Context

Agents can work on different projects simultaneously. Project context is scoped through:

- **Task description**: The natural language task statement carries project context
- **Semantic tagging**: Memory entries are tagged with project identifiers, allowing agents to retrieve project-specific insights with higher relevance
- **Jobs configuration**: `config/jobs.yaml` defines project-specific task patterns and execution logic
- **Worker specialization**: Workers can be assigned to specific projects via Temporal task queues, ensuring project isolation when needed

Cross-project insights still flow through the shared Qdrant instance — a Docker fix discovered in Project A is available to Project B if semantically relevant.

---

## Deployment Topology

### LAN Deployment (Primary)

```
[Raspberry Pi - Genesis CNC]
        |
        | (SSH / Temporal gRPC)
        v
[LAN Machine - Control Plane]
  Temporal | Qdrant | Redis | Postgres | LiteLLM
        |
        | (Temporal task queue)
        v
[LAN Machine(s) - Worker Nodes]
  Containerized, stateless, polling Temporal
```

### Cloud Deployment (On-Demand)

```
[Raspberry Pi - Genesis CNC]
        |
        | (Pulumi provision + Temporal gRPC)
        v
[Cloud VM - Control Plane]
  Temporal | Qdrant | Redis | Postgres | LiteLLM
        |
        | (Temporal task queue)
        v
[Cloud VM(s) - Worker Nodes]
  Provisioned via Pulumi, auto-scaled, ephemeral
```

### Hybrid (LAN Control + Cloud Workers)

```
[Raspberry Pi - Genesis CNC]
        |
        v
[LAN Machine - Control Plane]
        |
        +---> [LAN Worker - always-on, low-cost tasks]
        |
        +---> [Cloud Worker - burst capacity, GPU tasks]
```

---

## Offline Resilience

The Genesis Node operates reliably even when the Control Plane is temporarily unreachable:

1. Tasks are queued in a local SQLite database (`offline_queue.db`)
2. The scheduler retries the connection periodically
3. On reconnect, the offline queue is flushed to Temporal in order
4. The user is notified via Telegram when tasks transition from offline to submitted

This ensures the feedback loop is never broken by transient network issues.

---

## See Also

- [ARCHITECTURE.md](../ARCHITECTURE.md) — Full system topology and component descriptions
- [docs/agent_feedback_loop.md](agent_feedback_loop.md) — Detailed feedback cycle with code examples
- [docs/cluster_expansion.md](cluster_expansion.md) — Adding more worker nodes
- [docs/KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) — Operational lessons and known pitfalls
