#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — Full rebuild and redeploy for a specific plane or all planes.
#
# Works for LOCAL and REMOTE machines.
#
# Usage:
#   ./scripts/deploy.sh                                    # local, all planes
#   ./scripts/deploy.sh execution                          # local, execution only
#   ./scripts/deploy.sh execution --remote 192.168.100.100 # remote, execution
#   ./scripts/deploy.sh all --remote 192.168.100.100 --user pi --key ~/.ssh/id_rsa
#
# Planes: cnc | control | execution | infra | all
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
PLANE="all"
REMOTE_HOST=""
SSH_USER="${SSH_USER:-$(whoami)}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-~/ai-orchestrator-project}"
COMPOSE_FILE="src/execution/worker/docker-compose.yml"

# ── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) REMOTE_HOST="$2"; shift 2 ;;
    --user)   SSH_USER="$2";    shift 2 ;;
    --key)    SSH_KEY="$2";     shift 2 ;;
    --dir)    REMOTE_PROJECT_DIR="$2"; shift 2 ;;
    cnc|control|execution|infra|all) PLANE="$1"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

log() { echo "$(date '+%H:%M:%S') [$1] $2"; }

ssh_cmd() {
  local host="$1"; shift
  local key_opt=()
  [[ -n "$SSH_KEY" ]] && key_opt=(-i "$SSH_KEY")
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
      "${key_opt[@]}" "${SSH_USER}@${host}" "$@"
}

# ── Local deploy ──────────────────────────────────────────────────────────────
local_deploy() {
  log "GIT" "Pulling latest code from origin/main..."
  git pull --rebase origin main

  local compose_files=("-f" "$COMPOSE_FILE" "-f" "src/observability/docker-compose.observability.yml" "-f" "src/control/docker-compose.control.yml" "-f" "docker-compose.cnc.yml")
  local services=()

  case "$PLANE" in
    infra)
      log "INFRA" "Restarting infrastructure (no rebuild)..."
      docker compose "${compose_files[@]}" restart temporal postgres qdrant redis
      return
      ;;
    execution) services=(ai-worker) ;;
    observability) services=(collector web) ;;
    control) services=(dispatcher selector) ;;
    cnc) services=(cnc) ;;
    all) services=(ai-worker collector web dispatcher selector cnc) ;;
  esac

  log "$PLANE" "Pulling latest images from GHCR and restarting..."
  docker compose "${compose_files[@]}" pull "${services[@]}"
  docker compose "${compose_files[@]}" up -d --no-deps "${services[@]}"
  log "✅" "Local deploy of $PLANE complete."
  docker compose "${compose_files[@]}" ps "${services[@]}"
}

# ── Remote deploy (SSH) ───────────────────────────────────────────────────────
remote_deploy() {
  local host="$REMOTE_HOST"
  log "REMOTE" "Deploying $PLANE to $SSH_USER@$host..."

  if ! ssh_cmd "$host" "echo ok" &>/dev/null; then
    echo "❌ Cannot reach $host via SSH."
    exit 1
  fi

  log "REMOTE" "Pulling latest code on $host..."
  ssh_cmd "$host" "cd $REMOTE_PROJECT_DIR && git pull --rebase origin main"

  local compose_files=("-f" "$COMPOSE_FILE" "-f" "src/observability/docker-compose.observability.yml" "-f" "src/control/docker-compose.control.yml" "-f" "docker-compose.cnc.yml")
  local services=()

  case "$PLANE" in
    execution) services=(ai-worker) ;;
    observability) services=(collector web) ;;
    control) services=(dispatcher selector) ;;
    cnc) services=(cnc) ;;
    all) services=(ai-worker collector web dispatcher selector cnc) ;;
  esac

  log "REMOTE" "Pulling latest images from GHCR on $host..."
  ssh_cmd "$host" "cd $REMOTE_PROJECT_DIR && \
    docker compose ${compose_files[*]} pull ${services[*]} && \
    docker compose ${compose_files[*]} up -d --no-deps ${services[*]}"

  log "✅" "Remote deploy of $PLANE on $host complete."
}

main() {
  log "DEPLOY" "Plane: $PLANE | Target: ${REMOTE_HOST:-localhost}"
  if ! docker info &>/dev/null && [[ -z "$REMOTE_HOST" ]]; then
    echo "❌ Docker is not running locally."
    exit 1
  fi

  if [[ -n "$REMOTE_HOST" ]]; then
    remote_deploy
  else
    local_deploy
  fi
  log "DONE" "Deployment finished."
}

main
