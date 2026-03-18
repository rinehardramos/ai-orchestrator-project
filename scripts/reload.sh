#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# reload.sh — Fast hot-reload WITHOUT rebuilding the Docker image.
#
# How it works:
#   1. Syncs your local code into the running container using `docker cp`
#   2. Sends a SIGTERM to the Python process inside the container so it
#      restarts and picks up the new code.
#   This is ~5x faster than a full `docker-compose up --build`.
#
# Usage:
#   ./scripts/reload.sh              # hot-reload all running app containers
#   ./scripts/reload.sh execution    # hot-reload Execution Plane worker only
#   ./scripts/reload.sh cnc          # hot-reload CNC node only (same container for now)
#   ./scripts/reload.sh control      # hot-reload Control Plane services
#
# Requirements:
#   - The target container must be running.
#   - The container's CMD must auto-restart on SIGTERM (watchdog or supervisor).
#     For basic containers, this does a graceful container restart instead.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PLANE="${1:-all}"
WORKER_CONTAINER="central_node-ai-worker-1"
COMPOSE_FILE="src/execution/worker/docker-compose.yml"

log() { echo "$(date '+%H:%M:%S') [$1] $2"; }

sync_code() {
  local container="$1"
  log "SYNC" "Copying updated source code into $container..."
  docker cp src/. "$container":/app/src/
  docker cp config/. "$container":/app/config/ 2>/dev/null || true
  docker cp requirements.txt "$container":/app/requirements.txt 2>/dev/null || true
  log "SYNC" "Code sync complete."
}

restart_container() {
  local container="$1"
  local plane="$2"

  if ! docker inspect "$container" &>/dev/null; then
    log "WARN" "Container $container not found — skipping $plane reload."
    return
  fi

  log "$plane" "Restarting $container to apply new code..."
  docker restart "$container"
  log "✅" "$plane reloaded. New logs:"
  sleep 2
  docker logs "$container" --tail 10
}

reload_plane() {
  local plane="$1"

  case "$plane" in
    execution|cnc|control|all)
      sync_code "$WORKER_CONTAINER"
      restart_container "$WORKER_CONTAINER" "$plane"
      ;;
    *)
      echo "❌ Unknown plane: $plane. Use: execution | cnc | control | all"
      exit 1
      ;;
  esac
}

main() {
  log "RELOAD" "Hot-reloading plane: $PLANE"

  if ! docker info &>/dev/null; then
    echo "❌ Docker is not running."
    exit 1
  fi

  reload_plane "$PLANE"
  log "DONE" "Hot-reload complete. Run 'docker logs $WORKER_CONTAINER -f' to monitor."
}

main
