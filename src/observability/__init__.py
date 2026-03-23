"""
Observability Package
=====================
Opik self-hosted deployment for LLM tracing and observability.

Modules:
  - health_check: Minimal service health probes
  - collector: Node/container stats published to Redis pub/sub

Deployment:
  cd src/observability
  docker compose -f docker-compose.observability.yml --profile opik up -d

Access:
  - Opik UI: http://<host>:5173
  - Opik API: http://<host>:8080

Environment Variables:
  - OPIK_URL_OVERRIDE: Backend API URL for SDK (default: http://192.168.100.249:8080)
  - OPIK_PROJECT_NAME: Project name for trace grouping (default: ai-orchestration)
"""
