# AI System Lessons Learned

_Every time the user corrects a mistake, documents a bug, or provides a new paradigm, log the behavioral pattern to avoid in this file._

## Initialization
- **Resource Management**: When polling or accessing backend databases recursively (e.g., Temporal task history), do NOT inflate long-polling or WebSocket requests. Explicitly use on-demand REST API endpoints combined with lazy loading (like the Task Details Modal) to circumvent `N+1 Query Problems` and memory spikes.
- **Frontend Sync**: Docker Desktop volume mounts might mask internal UI updates if directories are misconfigured. If UI edits aren't appearing, force container recreation or explicitly `docker cp` to isolate where the files diverge.

## Architecture & Observability
- **Multi-Agent Decomposition**: For complex tasks, use a `Planner` node to generate a structured `ExecutionPlan`. Using LangGraph's `Send` API allows for dynamic scaling of parallel workers without hardcoding every possible node in the graph.
- **Redundant Metrics Friction**: Avoid multiple overlapping observability providers (e.g., Prometheus + Opik + Temporal). Consolidating into a single tracing provider (Opik) reduces initialization errors (like circular metric imports) and provides a more cohesive timeline for multi-agent execution.
- **State Update Robustness**: When working with sub-agent pipelines, prefer `ainvoke` over `astream` if you only need the final state. Manually iterating over `astream` events to `update()` a dictionary can lead to `ValueErrors` if the stream yields non-dictionary deltas (like message list reducers).
- **Import Guards**: Always guard heavy observability or optional packages (like `opik`) with `try-except` blocks in library code to ensure the core worker remains functional in environments where these packages are not installed.

## Ongoing Rules
- **Simple Over Complex**: "Senior developer standards. Minimal Impact. Changes should only touch what's necessary."
- **Self-Sufficiency**: "When given a bug report: just fix it. Don't ask for hand-holding. Go fix failing CI tests without being told how."
- **Proof Over Promises**: "Never mark a task complete without proving it works. Run tests, check logs, demonstrate correctness."
- **Variable Instantiation (CI Guards)**: Always locally verify that injected metrics, counters, and utility classes (such as `HybridStore`) are strictly instantiated in the script's global scope before committing. Undefined python namespaces will cause instant `F821` crashes in Github Action `flake8` linters.
- **Unit Test Integrity**: If you disable or disconnect an active logic path (e.g., semantic vector matching) within the project's orchestration classes, you MUST find and explicitly decorate the accompanying component unit tests with `@pytest.mark.skip`. Orphaned assertions on bypassed code routines will silently fail the master Github Actions pipeline.
