#!/bin/bash
# Start the Scheduler Daemon
# Usage: ./scripts/start_scheduler.sh

set -e

cd "$(dirname "$0")/.."

echo "Starting Scheduler Daemon..."

# Check if already running
if pgrep -f "start_scheduler.py" > /dev/null 2>&1; then
    echo "Scheduler daemon is already running"
    exit 0
fi

# Start in background
nohup python3 scripts/start_scheduler.py > logs/scheduler.log 2>&1 &

echo "Scheduler daemon started (PID: $!)"
echo "Logs: logs/scheduler.log"
