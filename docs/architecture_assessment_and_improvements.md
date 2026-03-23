# Architecture Assessment & Improvements

## Architecture Overview
Your architecture smartly decouples the user interface from heavy execution:
1. **Genesis Node (CNC - Raspberry Pi):** A thin L0 gateway that parses intent, performs pre-flight safety checks against the Knowledge Base, and delegates workflows.
2. **Control Plane (Central Node):** A robust state management layer using Temporal (orchestration), Qdrant (L2 persistent memory), and Redis (L1 ephemeral memory/checkpoints).
3. **Execution Plane (Remote Worker):** High-privilege execution containers driven by Langgraph reasoning loops, backed by Temporal's retry mechanisms.

---

## Improvements (Status Tracked)

> Legend: ✅ Implemented | 🔲 Pending

### 1. Optimization & Performance
*   🔲 **Tiered State Resumption:** Implement Temporal Data Converters to automatically compress or upload large Langgraph state payloads to L3 storage (S3) and only pass the S3 reference pointer through Temporal's event history.
*   ✅ **Pre-flight Caching on CNC:** Fast-expiring LRU cache on the Raspberry Pi for frequent tasks (`src/genesis/orchestrator/scheduler.py`).
*   🔲 **Persistent Connections:** Ensure the Pi maintains persistent gRPC connections to the Temporal Server rather than opening new connections per CLI command.

### 2. Cost Reduction
*   🔲 **Spot Instances / Preemptible VMs for Workers:** Use AWS Spot Instances or GCP Preemptible VMs for the Execution Plane.
*   🔲 **Scale-to-Zero Execution Plane:** Move worker execution containers to a serverless compute engine like AWS Fargate.
*   🔲 **Vector DB Optimization:** Transition Qdrant to a serverless offering (like Qdrant Cloud).

### 3. Security
*   🔲 **Temporal Payload Encryption:** Implement a custom Temporal Data Converter to encrypt inputs, outputs, and intermediate states.
*   🔲 **Zero-Trust Networking:** Wrap the communication layer in a mesh VPN (like Tailscale or WireGuard).
*   🔲 **Ephemeral Sandbox Execution:** Wrap subprocess execution in lightweight, ephemeral microVMs (like Firecracker) or strongly isolated sandboxes (like gVisor).

### 4. User Experience (UX)
*   🔲 **Real-time Streaming via Temporal Queries:** Implement Temporal Queries or an asynchronous WebSocket stream so the Genesis node can pull and display intermediate Langgraph steps.
*   ✅ **Interactive Pre-flight Resolution:** CLI prompts interactively when warnings are detected from KB pre-flight check.
*   ✅ **Local Queuing for Offline Mode:** Tasks submitted while offline are queued in SQLite (`offline_queue.db`) and auto-flushed on reconnect.

### 5. Data Safety & Monitoring
*   ✅ **Automated Backups:** `BackupManager` (`src/genesis/orchestrator/backup_manager.py`) orchestrates Qdrant and Temporal Postgres snapshots.
*   ✅ **Telegram Notifications:** `TelegramNotifier` sends real-time job status (submitted, running, complete, failed, blocked) to a configured Telegram channel.

### 6. Multi-Model & Unified LLM Access
*   ✅ **LiteLLM Proxy (Worker):** All LLM completion calls on the Execution Plane route through LiteLLM Router, enabling provider-agnostic model selection (Claude, Gemini, GPT-4, etc.). See `docs/litellm_integration.md`.
*   ✅ **Lightweight CNC Embeddings:** `KnowledgeBaseClient` uses direct HTTP calls to Google/OpenAI embedding APIs — no heavy ML libraries on the Pi. `requests` is the only dependency.
*   ✅ **Cost Tracking:** LiteLLM's `completion_cost()` is called after every LLM call in the worker. `total_cost_usd` is returned in the task result and surfaced in Telegram notifications.
*   🔲 **Full LiteLLM Migration:** Migrate CNC-side intent parser LLM calls to use LiteLLM (on worker proxy) for full unification.

### 7. Reliability & Correctness
*   ✅ **Real Backup Manager:** Qdrant Snapshot API and `pg_dump` subprocess replace the previous mock implementation. Gracefully handles Qdrant unavailability and missing `pg_dump`.
*   ✅ **Offline Queue Auto-Flush:** `flush_offline_queue()` resubmits locally queued tasks to Temporal on reconnect, called automatically at the start of each `submit_task()`.
*   ✅ **Pre-flight KB Lookup Re-enabled:** Removed the `if False:` guard. Pre-flight semantic search now runs on every task submission with LRU caching.
*   ✅ **Real Semantic Vectors in L2:** Worker embeds recommendations using `litellm.embedding()` before storing to Qdrant `agent_insights` — replacing the previous dummy `[0.1]*1536` vector.
*   ✅ **Config-driven Model Selector:** `selector.py` loads its model registry dynamically from `config/profiles.yaml` instead of a hardcoded list. Duplicate profile entry also fixed.