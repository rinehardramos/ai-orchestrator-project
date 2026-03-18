# AI Orchestration Project - Knowledge Base

This knowledge base documents repeated operations, common pitfalls, and their resolutions to prevent recurring mistakes in the AI Orchestration Project.

## 1. Task Delegation and Node Architecture
- **Issue:** Attempting to run shell commands or create application code directly on the CNC (Genesis) node.
- **Root Cause:** Bypassing the architectural rule that jobs (except repository code changes) should be triggered on worker nodes.
- **Resolution:** Use the Temporal scheduler (`src/orchestrator/scheduler.py`) to delegate tasks to the remote worker node queue (`ai-orchestration-queue`).

## 2. Remote Worker Interaction and Docker
- **Issue:** Running `docker ps` or `docker-compose` locally on the CNC node to find/manage the worker.
- **Root Cause:** The worker node runs remotely (e.g., at `192.168.100.249`), and the CNC node only delegates via Temporal.
- **Resolution:** Access the worker via SSH. Use `docker compose` (modern syntax) instead of `docker-compose` on the remote node.
- **Issue:** `docker compose` command not found during remote SSH execution.
- **Resolution:** Ensure the PATH is explicitly set in the SSH command (e.g., `PATH=$PATH:/usr/local/bin:/usr/bin docker compose ...`).

## 3. Python Virtual Environments
- **Issue:** `ModuleNotFoundError: No module named 'boto3'` when running Python scripts locally or via SSH.
- **Root Cause:** Running scripts using the system's global Python instead of the project's virtual environment.
- **Resolution:** Always use the project's virtual environment (`venv/bin/python`) when executing Python scripts.

## 4. Container Dependencies and Paths
- **Issue:** Missing binaries (`terraform`, `pulumi`, `aws-cdk`) when executing shell commands inside the worker container.
- **Resolution:** Install the required tools explicitly in `central_node/Dockerfile.worker` during the build phase. Remember to download architecture-appropriate binaries (e.g., `arm64` vs `amd64`) based on the host system architecture.
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
  - **Feature:** The CNC node can interface with multiple control planes and remote workers.
  - **Configuration:** Restructured `config/settings.yaml` to support named environments under the `environments` key. Use `active_environment` to set the default.
  - **Usage:** Use the `--env [name]` flag in `main.py` to switch environments at runtime.
  - **Pitfall:** If a new environment is added but not selected via `--env` or `active_environment`, the system may fallback to legacy top-level settings if they still exist.
  - **Resolution:** Always verify the loaded environment in the logs (e.g., `🔧 [CONFIG] Loading environment: ...`).