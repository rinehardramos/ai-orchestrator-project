# CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- **Observability Dashboard**: Added task tracking by mapping Temporal workflows (IDs and human-readable Statuses) to `obs:events` payloads.
- **Task Telemetry**: Scheduler now pushes task descriptions (content) as transient `SETEX` keys to Redis, mitigating unbounded memory growth.
- **Frontend Upgrades**: Added "Recent Tasks" grid panel to the web monitor UI, converting generic integer statuses (e.g., `1`, `2`) into elegant strings like "Running" or "Completed".

