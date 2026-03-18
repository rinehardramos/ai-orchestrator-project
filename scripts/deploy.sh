#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — Full rebuild and redeploy for a specific plane or all planes.
#
# Usage:
#   ./scripts/deploy.sh              # redeploy all planes
#   ./scripts/deploy.sh cnc          # rebuild + restart CNC/Genesis Node only
#   ./scripts/deploy.sh control      # rebuild + restart Control Plane services only
#   ./scripts/deploy.sh execution    # rebuild + restart Execution Plane worker only
#   ./scripts/deploy.sh infra        # restart infra (Temporal, Postgres, Qdrant, Redis)
#
# This performs a full Docker IMAGE rebuild (--build) then restarts the
# affected containers. Use reload.sh instead for fast code-only restarts.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

COMPOSE_FILE="src/execution/worker/docker-compose.yml"
PLANE="${1:-all}"

log() { echo "$(date '+%H:%M:%S') [$1] $2"; }

pull_latest() {
  log "GIT" "Pulling latest code from origin/main..."
  git pull --rebase origin main
}

rebuild_plane() {
  local plane="$1"
  local services=()

  case "$plane" in
    cnc)
      services=(ai-worker)   # CNC runs as a separate invocation; worker covers the shared image for now
      log "CNC" "Rebuilding Genesis Node (CNC)..."
      ;;
    control)
      services=(ai-worker)   # Control Plane services (dispatcher, catalog, etc.) — extend here as they get their own containers
      log "CONTROL" "Rebuilding Control Plane services..."
      ;;
    execution)
      services=(ai-worker)
      log "EXECUTION" "Rebuilding Execution Plane worker..."
      ;;
    infra)
      services=(temporal postgres qdrant redis)
      log "INFRA" "Restarting infrastructure services (no rebuild)..."
      docker compose -f "$COMPOSE_FILE" restart "${services[@]}"
      return
      ;;
    all)
      services=(ai-worker)
      log "ALL" "Rebuilding all application planes..."
      ;;
    *)
      echo "❌ Unknown plane: $plane. Use: cnc | control | execution | infra | all"
      exit 1
      ;;
  esac

  docker compose -f "$COMPOSE_FILE" up -d --build --no-deps "${services[@]}"
  log "✅" "Plane '$plane' redeployed. Containers:"
  docker compose -f "$COMPOSE_FILE" ps "${services[@]}"
}

main() {
  log "DEPLOY" "Starting deployment for plane: $PLANE"

  # Check docker compose is available
  if ! docker compose version &>/dev/null; then
    echo "❌ 'docker compose' not found. Please install Docker Desktop or Docker Compose plugin."
    exit 1
  fi

  pull_latest
  rebuild_plane "$PLANE"
  log "DONE" "Deployment complete."
}

main
