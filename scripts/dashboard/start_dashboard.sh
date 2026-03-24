#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Installing dashboard dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Starting dashboard server..."
cd "$PROJECT_ROOT"
python3 "$SCRIPT_DIR/start_dashboard.py" "$@"
