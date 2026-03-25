#!/bin/bash
# Install Scheduler Service on macOS (MacBook)
# Run this script once to set up the launchd service

set -e

PROJECT_DIR="/Users/rinehardramos/Projects/ai-orchestrator-project"
LOG_DIR="/var/log/ai-orchestrator"

echo "=== Installing AI Orchestrator Scheduler Service ==="

# Create log directory
echo "Creating log directory..."
sudo mkdir -p "$LOG_DIR"
sudo chown "$USER:staff" "$LOG_DIR"

# Copy plist to LaunchAgents
echo "Installing launchd plist..."
cp deployment/scheduler.macbook.plist ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist

# Load the service
echo "Loading scheduler service..."
launchctl load ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist

# Check status
sleep 2
echo ""
echo "=== Service Status ==="
launchctl list | grep aiorchestrator || echo "Service loaded"

echo ""
echo "=== Recent Logs ==="
tail -10 "$LOG_DIR/scheduler.log" 2>/dev/null || echo "No logs yet - service may be starting..."

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Commands:"
echo "  Status:   launchctl list | grep aiorchestrator"
echo "  Stop:     launchctl unload ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist"
echo "  Start:    launchctl load ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist"
echo "  Restart:  launchctl unload ... && launchctl load ..."
echo "  Logs:     tail -f $LOG_DIR/scheduler.log"
