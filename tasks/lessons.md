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

## Model Configuration & Provider Routing
- **Always validate model IDs against provider docs before committing**: Phantom model IDs like `gemini-3-flash` silently return 404 at runtime, not at config load time. The fallback chain then tries OpenRouter — which also fails without a key — making the entire system dead with no obvious error.
- **SAFE_FALLBACK_MODEL must match its fallback call path**: If `SAFE_FALLBACK_MODEL` names a Google-native model, the fallback call must use `_call_google`, not `_call_remote` (OpenRouter). Mismatching model name and call path is a guaranteed 401/404.
- **Provider-specific clients require full feature implementation**: The `_call_google` implementation did not pass tools or parse function calls. The agent appeared to work (LLM returned text), but tools were never called — the model hallucinated tool results. Any new provider client must handle: tool schema conversion, function call response parsing, and tool result re-encoding on the conversation turn.

## Multi-Agent Orchestrator
- **`coordinated_team` requires data dependency, not just sequential steps**: The planner prompt must be explicit that `single_agent` is the default for any task one agent can handle in one session — including multi-step tasks with file I/O. `coordinated_team` is only justified when the output of agent A is a required input for agent B's task description. Without this constraint, the planner over-splits simple tasks.
- **Never bypass the orchestrator pipeline**: Any fast-path that calls tools or LLMs before `run_orchestrator` violates the architecture and breaks `parallel_isolated` and `coordinated_team` strategies. All execution must flow through `planner_node → orchestrator_router → subtask_worker`.
- **Genesis node must not run worker processes**: The genesis (CNC) node is task delegation only. A native `worker.py` process running on the genesis node will race the Docker container for Temporal tasks and process them with stale in-memory config, producing incorrect results silently.

## Self-Healing & Dynamic Tool Registration
- **Recovery loops need an explicit exit condition, not just a boolean gate**: `recovery_attempted=True` prevents re-entering the recovery node, but if the retry still fails with the same pattern, `synthesis_node` must explicitly return `status="failed"` — not `"completed"`. Silently marking a failed retry as completed hides the failure and misleads the caller.
- **Emit heartbeats at every major phase boundary, not just agent steps**: Recovery milestones (`recovery_analyzing`, `recovery_retry`) are as important to communicate as LLM call progress. The scheduler's heartbeat loop is already polling — use it. Custom phase names give the scheduler the signal it needs to send targeted, meaningful messages instead of generic "📈 Progress" lines.
- **Dynamic tool registration must be visible to both schemas and dispatch**: Adding a tool to `_DYNAMIC_REGISTRY` is only half the job. `get_tool_schemas()` must include it (so the LLM sees it in its context) AND `get_tool_fn()` must resolve it (so the tool dispatcher can call it). Both lookups must check the registry.
- **Persist generated tools via volume-mounted files, not in-memory only**: `exec()`-registered tools are lost on container restart. Appending the function and `TOOL_REGISTRY` entry to `tools.py` via the volume-mounted path makes the fix durable without image rebuilds.

## Ongoing Rules
- **Simple Over Complex**: "Senior developer standards. Minimal Impact. Changes should only touch what's necessary."
- **Self-Sufficiency**: "When given a bug report: just fix it. Don't ask for hand-holding. Go fix failing CI tests without being told how."
- **Proof Over Promises**: "Never mark a task complete without proving it works. Run tests, check logs, demonstrate correctness."
- **Variable Instantiation (CI Guards)**: Always locally verify that injected metrics, counters, and utility classes (such as `HybridStore`) are strictly instantiated in the script's global scope before committing. Undefined python namespaces will cause instant `F821` crashes in Github Action `flake8` linters.
- **Unit Test Integrity**: If you disable or disconnect an active logic path (e.g., semantic vector matching) within the project's orchestration classes, you MUST find and explicitly decorate the accompanying component unit tests with `@pytest.mark.skip`. Orphaned assertions on bypassed code routines will silently fail the master Github Actions pipeline.
