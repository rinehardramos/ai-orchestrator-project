# AI Orchestrator TODO List

### Features
- [x] Multi-Agent Orchestrator with dynamic task decomposition and parallel execution.
- [ ] Implement advanced error recovery protocols for long-running Temporal task executions.
- [ ] Integration with real SOTA media APIs (Luma Dream Machine, Suno v4, Sora) for `generate_video` and `generate_audio` tools.
- [ ] Add agent "Co-Pilot" mode where agents can request human intervention for ambiguous tasks.
- [ ] Add timeline graphs or latency heatmaps to the Observability Dashboard for worker nodes.
- [ ] Introduce full-text search across the historical task database (Qdrant).

### Fixes
- [x] Resolved circular import and Redundant Prometheus metrics initialization in multi-agent worker environments.
- [x] Fixed `duckduckgo_search` package import compatibility.
- [ ] Address strict mode violations and timing sensitivities in the Playwright integration tests.
- [ ] Optimize the memory decay loops in `hybrid_store.py` to prevent stale task metadata accumulation.
