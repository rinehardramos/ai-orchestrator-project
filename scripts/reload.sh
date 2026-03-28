#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# reload.sh — Hot-reload code into a running plane WITHOUT rebuilding images.
#
# Works for:
#   LOCAL  — Docker is running on this machine
#   REMOTE — Connects via SSH to a remote worker node, pulls latest code, restarts
#
# Usage:
#   ./scripts/reload.sh                            # local, all planes
#   ./scripts/reload.sh execution                  # local, Execution Plane only
#   ./scripts/reload.sh execution --remote 192.168.100.100         # remote SSH
#   ./scripts/reload.sh execution --remote 192.168.100.100 --user pi
#   ./scripts/reload.sh all --remote 192.168.100.100 --key ~/.ssh/id_rsa
#
# Requirements (remote):
#   - SSH access to the remote machine
#   - Docker running on the remote machine
#   - The project already cloned at REMOTE_PROJECT_DIR on the remote machine
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
PLANE="all"
REMOTE_HOST=""
SSH_USER="${SSH_USER:-$(whoami)}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-~/ai-orchestrator-project}"
# CONTAINER_NAME can be overridden via env var; defaults to the standalone deploy container
# but we will also check for the generic 'ai-worker' as a fallback.
WORKER_CONTAINER="${WORKER_CONTAINER:-deploy-ai-worker-1}"
FALLBACK_CONTAINER="ai-worker"

# ── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)  REMOTE_HOST="$2"; shift 2 ;;
    --user)    SSH_USER="$2";    shift 2 ;;
    --key)     SSH_KEY="$2";     shift 2 ;;
    --dir)     REMOTE_PROJECT_DIR="$2"; shift 2 ;;
    cnc|control|execution|infra|all) PLANE="$1"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

log() { echo "$(date '+%H:%M:%S') [$1] $2"; }

# ── SSH helper ────────────────────────────────────────────────────────────────
ssh_cmd() {
  local host="$1"; shift
  local key_opt=()
  [[ -n "$SSH_KEY" ]] && key_opt=(-i "$SSH_KEY")
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
      "${key_opt[@]}" "${SSH_USER}@${host}" "$@"
}

# ── Local reload ──────────────────────────────────────────────────────────────
local_reload() {
  local container="$WORKER_CONTAINER"

  if ! docker inspect "$container" &>/dev/null; then
    if [[ "$container" == "$WORKER_CONTAINER" ]] && docker inspect "$FALLBACK_CONTAINER" &>/dev/null; then
      log "INFO" "Target $container not found, falling back to $FALLBACK_CONTAINER..."
      container="$FALLBACK_CONTAINER"
    else
      log "WARN" "Container $container not running — skipping."
      return
    fi
  fi

  log "SYNC" "Copying updated source code into $container..."
  docker cp src/. "$container":/app/src/
  docker cp config/. "$container":/app/config/ 2>/dev/null || true
  log "SYNC" "Code sync complete."

  log "$PLANE" "Restarting $container..."
  docker restart "$container"
  sleep 2
  log "✅" "Local reload complete. Tail logs with: docker logs $container -f"
}

# ── Remote reload (SSH) ───────────────────────────────────────────────────────
remote_reload() {
  local host="$REMOTE_HOST"
  log "REMOTE" "Connecting to $SSH_USER@$host..."

  # Verify SSH connectivity first
  if ! ssh_cmd "$host" "echo ok" &>/dev/null; then
    echo "❌ Cannot reach $host via SSH. Check IP, user, and key."
    exit 1
  fi
  log "REMOTE" "SSH connection established."

  # 1. Pull latest code on the remote machine
  log "REMOTE" "Pulling latest code on $host..."
  ssh_cmd "$host" "cd $REMOTE_PROJECT_DIR && git pull --rebase origin main"

  # 2. Restart the container on the remote machine
  log "REMOTE" "Restarting containers on $host..."
  ssh_cmd "$host" "cd $REMOTE_PROJECT_DIR && docker restart $WORKER_CONTAINER 2>/dev/null || \
    docker compose -f src/execution/worker/docker-compose.worker.yml restart ai-worker"

  sleep 2

  # 3. Tail the remote logs briefly
  log "REMOTE" "Last 10 lines from remote worker:"
  ssh_cmd "$host" "docker logs $WORKER_CONTAINER --tail 10 2>/dev/null || \
    docker compose -f $REMOTE_PROJECT_DIR/src/execution/worker/docker-compose.worker.yml logs --tail 10 ai-worker"

  log "✅" "Remote reload of $host complete."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  log "RELOAD" "Plane: $PLANE | Target: ${REMOTE_HOST:-localhost}"

  if [[ -n "$REMOTE_HOST" ]]; then
    remote_reload
  else
    local_reload
  fi

  log "DONE" "Reload finished."
}

main
