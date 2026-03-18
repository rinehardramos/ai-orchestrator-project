#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# reload_all_nodes.sh — Rolling reload across every registered cluster node.
#
# The CNC (Genesis Node) calls this script after detecting code changes
# (e.g., on git push or via the Coordinator service).
#
# Node registry: config/cluster_nodes.yaml (see below for format).
# 
# Usage:
#   ./scripts/reload_all_nodes.sh              # reload all nodes
#   ./scripts/reload_all_nodes.sh --plane execution  # reload execution workers only
#   ./scripts/reload_all_nodes.sh --deploy     # full rebuild on all nodes (slow)
#
# cluster_nodes.yaml format:
#   nodes:
#     - name: genesis
#       host: localhost
#       role: cnc
#     - name: worker-1
#       host: 192.168.100.100
#       role: execution
#       user: pi
#       key: ~/.ssh/id_rsa
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PLANE="all"
FULL_DEPLOY=false
NODES_FILE="config/cluster_nodes.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plane)   PLANE="$2";     shift 2 ;;
    --deploy)  FULL_DEPLOY=true; shift ;;
    *)         echo "Unknown: $1"; exit 1 ;;
  esac
done

log() { echo "$(date '+%H:%M:%S') [$1] $2"; }

# Parse YAML manually (no yq dependency)
parse_nodes() {
  python3 - <<'EOF'
import yaml, sys, os

nodes_file = os.environ.get("NODES_FILE", "config/cluster_nodes.yaml")
if not os.path.exists(nodes_file):
    print("ERROR: cluster_nodes.yaml not found", file=sys.stderr)
    sys.exit(1)

with open(nodes_file) as f:
    data = yaml.safe_load(f)

for n in data.get("nodes", []):
    host = n.get("host", "localhost")
    user = n.get("user", "")
    key  = n.get("key", "")
    role = n.get("role", "execution")
    name = n.get("name", host)
    print(f"{name}|{host}|{user}|{key}|{role}")
EOF
}

reload_node() {
  local name="$1" host="$2" user="$3" key="$4" role="$5"
  local script="$SCRIPT_DIR/reload.sh"
  local args=("$PLANE")

  [[ "$host" != "localhost" ]] && args+=(--remote "$host")
  [[ -n "$user" ]] && args+=(--user "$user")
  [[ -n "$key" ]]  && args+=(--key "$key")

  if $FULL_DEPLOY; then
    script="$SCRIPT_DIR/deploy.sh"
  fi

  log "$name" "Reloading $role node at $host..."
  if bash "$script" "${args[@]}"; then
    log "✅" "$name ($host) — done"
  else
    log "❌" "$name ($host) — FAILED (continuing...)"
  fi
}

main() {
  if [[ ! -f "$NODES_FILE" ]]; then
    log "WARN" "$NODES_FILE not found. Creating default registry..."
    mkdir -p config
    cat > "$NODES_FILE" <<'YAML'
# Cluster Node Registry
# Add all machines in your cluster here.
nodes:
  - name: genesis
    host: localhost
    role: cnc

  # Add your remote worker machines below:
  # - name: worker-rpi
  #   host: 192.168.100.100
  #   role: execution
  #   user: pi
  #   key: ~/.ssh/id_rsa
YAML
    log "INFO" "Default $NODES_FILE created. Edit it to add remote nodes, then re-run."
    exit 0
  fi

  log "CLUSTER" "Starting rolling reload | Plane: $PLANE | Full deploy: $FULL_DEPLOY"
  log "CLUSTER" "Reading nodes from $NODES_FILE..."

  local failed=0
  while IFS='|' read -r name host user key role; do
    reload_node "$name" "$host" "$user" "$key" "$role" || ((failed++)) || true
  done < <(NODES_FILE="$NODES_FILE" parse_nodes)

  if [[ $failed -gt 0 ]]; then
    log "WARN" "$failed node(s) failed to reload. Check logs above."
    exit 1
  fi
  log "DONE" "All nodes reloaded successfully."
}

main
