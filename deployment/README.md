# AI Orchestrator - Scheduler Service

This directory contains service configurations for the scheduler daemon.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              MacBook.local (192.168.100.250) - CONTROL PLANE                │
│                                                                              │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌───────────────┐  │
│   │   Web UI    │   │   Postgres  │   │  Temporal   │   │   SCHEDULER   │  │
│   │  :8000      │   │   :5432     │   │   :7233     │   │   (daemon)    │  │
│   └─────────────┘   └─────────────┘   └─────────────┘   └───────────────┘  │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      WORKERS (Execution Plane)                       │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│         Genesis Node / Raspberry Pi (192.168.100.253) - CNC ONLY            │
│                                                                              │
│   - Task delegation (submits to Temporal on MacBook)                        │
│   - Infrastructure provisioning (terraform, pulumi, cdk)                    │
│   - Uses CRON for periodic maintenance tasks                                │
│   - Does NOT run scheduler daemon                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## MacBook Installation (Control Plane)

### Option 1: Manual (nohup)
```bash
cd /Users/rinehardramos/Projects/ai-orchestrator-project
source .venv/bin/activate
nohup python scripts/start_scheduler.py > /tmp/scheduler.log 2>&1 &
```

### Option 2: launchd (recommended for production)
```bash
./deployment/install_scheduler_macos.sh
```

### launchd Commands
```bash
# Check status
launchctl list | grep aiorchestrator

# Stop
launchctl unload ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist

# Start
launchctl load ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist && \
launchctl load ~/Library/LaunchAgents/com.aiorchestrator.scheduler.plist

# View logs
tail -f /var/log/ai-orchestrator/scheduler.log
```

## Genesis Node / Raspberry Pi (CNC Only)

The Genesis node does NOT run the scheduler daemon. Instead, use cron jobs for periodic tasks.

### Example Crontab for Genesis Node
```bash
# Edit crontab
crontab -e

# Add these lines:
# Check for infrastructure drift every 6 hours
0 */6 * * * /home/pi/ai-orchestrator-project/.venv/bin/python /home/pi/ai-orchestrator-project/scripts/check_drift.py

# Clean up old logs weekly
0 0 * * 0 find /var/log/ai-orchestrator -name "*.log" -mtime +30 -delete

# Sync configurations daily
0 2 * * * /home/pi/ai-orchestrator-project/.venv/bin/python /home/pi/ai-orchestrator-project/scripts/sync_config.py
```

## Environment Variables Required

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string |
| `CONFIG_SECRET_KEY` | AES-256 key for credential encryption |
| `TEMPORAL_ADDRESS` | Temporal server address (default: localhost:7233) |

## Task Types

| Type | Where it Executes |
|------|-------------------|
| `shell` | On MacBook (control plane) |
| `agent` | Via Temporal → Workers |
| `tool` | On MacBook (control plane) |
| `workflow` | Via Temporal |

## Monitoring

### Web UI
Navigate to `http://192.168.100.250:8000/ui/schedules` to:
- View scheduler daemon status
- Create/edit/delete scheduled tasks
- See execution history
- Monitor task failures

### API Endpoints
```bash
# Scheduler status
curl http://localhost:8000/api/schedules/daemon/status

# List tasks
curl http://localhost:8000/api/schedules

# Create task
curl -X POST http://localhost:8000/api/schedules \
  -H "Content-Type: application/json" \
  -d '{"name": "...", "schedule_type": "once", ...}'
```
