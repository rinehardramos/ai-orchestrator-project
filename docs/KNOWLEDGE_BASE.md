# AI Orchestration Project - Knowledge Base

This knowledge base documents repeated operations, common pitfalls, and their resolutions to prevent recurring mistakes in the AI Orchestration Project.

## 1. Task Delegation and Node Architecture
- **Issue:** Attempting to run shell commands or create application code directly on the Genesis (Genesis) node.
- **Root Cause:** Bypassing the architectural rule that jobs (except repository code changes) should be triggered on worker nodes.
- **Resolution:** Use the Temporal scheduler (`src/orchestrator/scheduler.py`) to delegate tasks to the remote worker node queue (`ai-orchestration-queue`).

## 2. Remote Worker Interaction and Docker
- **Issue:** Running `docker ps` or `docker-compose` locally on the Genesis node to find/manage the worker.
- **Root Cause:** The worker node runs remotely (e.g., at `macbook.local`), and the Genesis node only delegates via Temporal.
- **Resolution:** Access the worker via SSH. Use `docker compose` (modern syntax) instead of `docker-compose` on the remote node.
- **Issue:** `docker compose` command not found during remote SSH execution.
- **Resolution:** Ensure the PATH is explicitly set in the SSH command (e.g., `PATH=$PATH:/usr/local/bin:/usr/bin docker compose ...`).

## 3. Python Virtual Environments
- **Issue:** `ModuleNotFoundError: No module named 'boto3'` when running Python scripts locally or via SSH.
- **Root Cause:** Running scripts using the system's global Python instead of the project's virtual environment.
- **Resolution:** Always use the project's virtual environment (`venv/bin/python`) when executing Python scripts.

## 4. Container Dependencies and Paths
- **Issue:** Missing binaries (`terraform`, `pulumi`, `aws-cdk`) when executing shell commands inside the worker container.
- **Resolution:** Install the required tools explicitly in `src/execution/worker/Dockerfile.worker` during the build phase. Remember to download architecture-appropriate binaries (e.g., `arm64` vs `amd64`) based on the host system architecture.
- **Issue:** "Directory not found" errors when looking for IaC tools inside the worker container.
- **Resolution:** Verify the exact directory structure of the repository on the target node. For example, `iac-demo` contained an `infrastructure` subdirectory which housed the tools, requiring the base execution path to be updated to `iac-demo/infrastructure`.

## 5. macOS Docker Keychain Issue
- **Issue:** Provisioning to a macOS worker fails with `keychain cannot be accessed`.
- **Root Cause:** Docker attempts to use the interactive macOS keychain in a non-interactive SSH session.
- **Resolution:** Run the following command on the remote macOS worker to disable the credential helper for the automated session:
  ```bash
  mkdir -p ~/.docker
  echo '{"credsStore": ""}' > ~/.docker/config.json
  ```
  Alternatively, ensure the Genesis node environment variables are set to bypass the credential helper during deployment.

  ## 6. Multi-Environment Support
  - **Feature:** The Genesis node can interface with multiple control planes and remote workers.
  - **Configuration:** Restructured `config/settings.yaml` to support named environments under the `environments` key. Use `active_environment` to set the default.
  - **Usage:** Use the `--env [name]` flag in `main.py` to switch environments at runtime.
  - **Pitfall:** If a new environment is added but not selected via `--env` or `active_environment`, the system may fallback to legacy top-level settings if they still exist.
  - **Resolution:** Always verify the loaded environment in the logs (e.g., `🔧 [CONFIG] Loading environment: ...`).

## 7. Deployment and Command Triggering (Ansible)

The recommended way to deploy or reload services across your cluster is using the Ansible playbook. This ensures consistency, uses the correct SSH credentials (from `config/cluster_nodes.yaml`), and provides robust state management.

### Ansible Playbook (`scripts/deploy.yml`)

This playbook handles full rebuilds and restarts of specific planes or individual nodes.

**Variables:**
- `plane`: (str, default: `all`) — Specifies which logical plane to deploy (`cnc`, `control`, `execution`, `observability`, `infra`, `all`).
- `full_build`: (bool, default: `false`) — Set to `true` to force a Docker image rebuild for the targeted services.

**Examples:**

1.  **Full rebuild of the `observability` plane on the `worker-main` node:**
    ```bash
    ansible-playbook -i scripts/inventory.py scripts/deploy.yml -e "plane=observability full_build=true" --limit worker-main
    ```

2.  **Reload all services on all `execution_nodes` (fast, no image rebuild):**
    ```bash
    ansible-playbook -i scripts/inventory.py scripts/deploy.yml -e "plane=execution" --limit execution_nodes
    ```

3.  **Deploy all services on a specific node (e.g., `macbook.local`):**
    ```bash
    ansible-playbook -i scripts/inventory.py scripts/deploy.yml --limit worker-main
    ```
    (Note: `plane` defaults to `all` if not specified)

4.  **Reload a specific plane (e.g., `control`) on all relevant nodes without rebuilding images:**
    ```bash
    ansible-playbook -i scripts/inventory.py scripts/deploy.yml -e "plane=control"
    ```

**Important:**
-   Always use `-i scripts/inventory.py` to ensure Ansible fetches the correct host details (user, IP, SSH key) from `config/cluster_nodes.yaml`.
-   Use `--limit <hostname>` or `--limit <group_name>` to target specific hosts or groups defined in your inventory.

## 8. Dual Embedding System with Named Vectors

The knowledge store uses Qdrant named vectors to support dual embeddings in a single collection.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  KNOWLEDGE_V1 COLLECTION                         │
│                  (Single Collection)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Each Point Has NAMED VECTORS:                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │ vector["text"]      │  │ vector["code"]      │              │
│  │ Dim: 768            │  │ Dim: 3584           │              │
│  │ Model: nomic-text   │  │ Model: nomic-code   │              │
│  │ For: docs, resumes  │  │ For: code, APIs     │              │
│  └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
│  Query: query_points(using="text" | "code")                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Benefits

1. **Single Collection**: No need to manage multiple collections
2. **Dual Search**: Query same content using text OR code similarity
3. **Flexible Retrieval**: Use `search_both=True` to combine results
4. **No Dimension Mismatch**: Each vector space is independent

### Configuration

Embedding models are configured via database (`app_config` table):

```python
# task_routing.embeddings_text
{
    "model": "nomic-embed-text-v1.5",
    "provider": "lmstudio", 
    "dim": 768
}

# task_routing.embeddings_code
{
    "model": "nomic-embed-code",
    "provider": "lmstudio",
    "dim": 3584
}
```

### Usage

```python
from src.shared.memory.knowledge_store import get_store

store = get_store()

# Auto-detect content type and use appropriate vector
results = store.query("How do I authenticate with OAuth?", embed_type="auto")

# Search using text embeddings only
results = store.query("machine learning basics", embed_type="text")

# Search using code embeddings only
results = store.query("def authenticate():", embed_type="code")

# Search both vectors and merge results
results = store.query("API authentication", search_both=True)
```

### Content Classification

Content is automatically classified based on:
1. File extension (`.py`, `.js` → code)
2. Category metadata (`resume` → text)
3. Code pattern detection (regex heuristics)