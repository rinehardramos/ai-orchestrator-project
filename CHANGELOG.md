# CHANGELOG

All notable changes to this project will be documented in this file.

## [2026-03-19]
### Added
- **Observability Dashboard**: Added task tracking by mapping Temporal workflows (IDs and human-readable Statuses) to `obs:events` payloads.
- **Task Telemetry**: Scheduler now pushes task descriptions (content) as transient `SETEX` keys to Redis, mitigating unbounded memory growth.
- **Frontend Upgrades**: Added "Recent Tasks" grid panel to the web monitor UI, converting generic integer statuses (e.g., `1`, `2`) into elegant strings like "Running" or "Completed".
- Added `CHANGELOG.md`, `TODO.md`, and an agent memory rule to ensure these files are updated continuously.

### Changed
- Refactored `AnalyzerAgent` to `TaskAnalyzer` and updated file naming.
- Improved LiteLLM Router for dynamic tier-based model selection.
- Switched worker builds to local, updated models, and fixed GenAI cleanup issues.
- Integrated L1/L2/L3 storage latency metrics to Observability dashboard, plus YOLO mode and Telegram summaries.
- Adjusted Observability UI CSS grid so LLM Providers populate the top right layout slot.

### Fixed
- Corrected Temporal active/failed metric collections in Observability and replaced deprecated model-selector REST API with direct `profiles.yaml` config parsing.
- Improved task completion notifications and deployment robustness in CNC.
- Fixed LiteLLM router provider mapping and API key handling in the worker.
- Updated config to use `gemini-3-flash-preview`.
- Ensured correct LiteLLM provider prefixing in the worker.
- Added missing `prometheus-client` dependency.
- Fixed AWS CLI architecture parsing in `Dockerfile.cnc` and disabled Trivy exit on vulnerabilities.
- Resolved Pulumi `ModuleNotFoundError` by installing CLI and CNC dependencies.
- Resolved macOS Docker keychain issue by disabling `credsStore` in `~/.docker/config.json`.
- Fixed Redis subscriber loop and WebSocket protocol in the Observability plane.
- Mapped correct inclusion paths and build contexts for remote Mac deployments.
- Skipped worker checks for other planes in the `deploy.sh` verification.

## [2026-03-18]
### Added
- Added memory watchdog, crash prevention and Ansible inventory mapping in CNC.
- Implemented self-improving OODA loop, belief decay, and architectural analytics.
- Integrated `litellm` into the architecture for the control plane.
- Completed automated update integration with Watchtower and GHCR.
- Implemented robust CI/CD with GitHub Actions and GHCR publishing.
- Completed Observability CLI monitoring tool.
- Implemented Phase 1+3 of the Observability Plane.
- Implemented Ansible + Watchtower scripts for cluster-wide deployments and auto hot-reload.
- Added `deploy.sh` and `reload.sh` for targeted hot-reloading and plane redeployments.
- Introduced live integration tests for end-to-end task execution.
- Implemented balance-based model switching in the core.
- Refactored to Genesis Node architecture with Temporal delegation and automated remote provisioning.

### Changed
- Realigned all planes with `ghcr.io/owner/repo/service` naming conventions.
- Updated GitHub Actions to `v6` and configured Env vars to suppress Node.js 20 deprecation warnings.
- Added Trivy vulnerability scanning and Bandit security scanning to the pipeline.
- Major project restructuring dividing the codebase cleanly into distinct control, execution, and observability planes.
- Removed IaC antipatterns from Execution Plane to adhere to standard architectural boundaries.

### Fixed
- Fixed workflow step output references in GitHub Actions.
- Corrected Observability initialization to prevent Prometheus metric re-registration on startup.
- Fixed Watchtower DOCKER_API_VERSION for broad compatibility.
- Added absolute `project_dir` definitions for Genesis Node in `cluster_nodes.yaml`.
- Resolved failing tests originating from IaC execution refactors.

## [2026-03-17]
### Added
- Orchestrated fundamental tiered memory architecture.
- Initialized base integration for LangGraph and Temporal.
- Initial project commit establishing the core repository blueprint.
