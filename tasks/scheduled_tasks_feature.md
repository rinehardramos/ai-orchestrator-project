# Scheduled Tasks Feature (Cron-like Scheduler)

## Overview

Implement a cron-like task scheduling system that allows users to schedule prompts and tasks to run automatically at specified intervals or times.

## Architecture

```
Genesis Node (CNC)
├── SchedulerDaemon (background process)
├── SchedulerAPI (REST endpoints)
├── SchedulerWebUI (dashboard)
└── Database (scheduled_tasks table)

Worker Node (Execution)
└── Temporal Worker (executes scheduled tasks)
```

## User Stories

### Wave 1: Database & Core Models

#### US-1.1: Database Migration
**Priority:** High | **Estimate:** 1h | **Dependencies:** None

**As a** system
**I want** database tables for scheduled tasks
**So that** schedules can be persisted and tracked

**Acceptance Criteria:**
- [ ] Create `migrations/002_scheduled_tasks.sql`
- [ ] Table `scheduled_tasks` with columns:
  - id, uuid, name, description
  - schedule_type (cron/interval/once)
  - cron_expression, interval_seconds, scheduled_for
  - task_type, task_payload
  - enabled, status, last_run_at, next_run_at
  - run_count, failure_count, max_failures
  - notification settings
- [ ] Table `scheduled_task_history` for execution logs
- [ ] Indexes for performance
- [ ] Triggers for auto-updating timestamps
- [ ] Migration runs successfully on database

**Files:**
- `migrations/002_scheduled_tasks.sql`

---

#### US-1.2: ScheduledTask Model
**Priority:** High | **Estimate:** 1h | **Dependencies:** US-1.1

**As a** developer
**I want** a Pydantic model for scheduled tasks
**So that** the data structure is validated consistently

**Acceptance Criteria:**
- [ ] Create `src/genesis/scheduler/models.py`
- [ ] `ScheduledTaskCreate` schema for creating tasks
- [ ] `ScheduledTaskUpdate` schema for updating tasks
- [ ] `ScheduledTaskResponse` schema for API responses
- [ ] `ScheduledTaskInDB` schema for database representation
- [ ] `TaskHistoryResponse` schema for history
- [ ] Validate cron expressions
- [ ] Validate interval_seconds > 0
- [ ] Validate scheduled_for is in the future for 'once' type

**Files:**
- `src/genesis/scheduler/models.py`

---

### Wave 2: Scheduler Daemon

#### US-2.1: Cron Parser
**Priority:** High | **Estimate:** 1h | **Dependencies:** US-1.2

**As a** scheduler
**I want** to parse and evaluate cron expressions
**So that** I can determine when tasks should run

**Acceptance Criteria:**
- [ ] Create `src/genesis/scheduler/parser.py`
- [ ] Use `croniter` library for parsing
- [ ] Function `get_next_run(cron_expression, timezone) -> datetime`
- [ ] Function `validate_cron(cron_expression) -> bool`
- [ ] Support standard 5-field cron: `minute hour day month weekday`
- [ ] Support timezone-aware evaluation
- [ ] Handle invalid expressions gracefully

**Files:**
- `src/genesis/scheduler/parser.py`
- Add `croniter` to requirements.txt

---

#### US-2.2: Task Executor
**Priority:** High | **Estimate:** 2h | **Dependencies:** US-1.2

**As a** scheduler
**I want** to execute scheduled tasks via Temporal
**So that** tasks run on the worker node

**Acceptance Criteria:**
- [ ] Create `src/genesis/scheduler/executor.py`
- [ ] Function `execute_task(task: ScheduledTask) -> str` (returns task_id)
- [ ] Submit task to Temporal via existing `TaskScheduler`
- [ ] Support task types: `agent`, `shell`, `tool`
- [ ] Handle execution errors and timeouts
- [ ] Update task status in database
- [ ] Record execution in history table
- [ ] Send notifications on success/failure

**Files:**
- `src/genesis/scheduler/executor.py`

---

#### US-2.3: Scheduler Daemon
**Priority:** High | **Estimate:** 2h | **Dependencies:** US-2.1, US-2.2

**As a** system
**I want** a background daemon that checks and runs scheduled tasks
**So that** tasks execute automatically at their scheduled times

**Acceptance Criteria:**
- [ ] Create `src/genesis/scheduler/daemon.py`
- [ ] `SchedulerDaemon` class with `run()` method
- [ ] Poll database every 60 seconds for due tasks
- [ ] Calculate `next_run_at` for cron tasks using parser
- [ ] Execute tasks that are due (next_run_at <= now)
- [ ] Update `last_run_at`, `next_run_at`, `run_count` after execution
- [ ] Handle consecutive failures and disable after max_failures
- [ ] Graceful shutdown on SIGTERM/SIGINT
- [ ] Logging for debugging and monitoring

**Files:**
- `src/genesis/scheduler/daemon.py`

---

#### US-2.4: Daemon Startup Script
**Priority:** High | **Estimate:** 0.5h | **Dependencies:** US-2.3

**As a** operator
**I want** to start the scheduler daemon as a background process
**So that** scheduled tasks run continuously

**Acceptance Criteria:**
- [ ] Create `scripts/start_scheduler.py`
- [ ] Load environment variables
- [ ] Initialize database connection
- [ ] Start SchedulerDaemon
- [ ] Handle startup errors gracefully
- [ ] Can run as systemd service or Docker container

**Files:**
- `scripts/start_scheduler.py`

---

### Wave 3: REST API

#### US-3.1: Schedule CRUD API
**Priority:** High | **Estimate:** 2h | **Dependencies:** US-1.2

**As a** user
**I want** REST API endpoints to manage scheduled tasks
**So that** I can create, read, update, and delete schedules

**Acceptance Criteria:**
- [ ] Create `src/genesis/api/schedules.py`
- [ ] `GET /api/schedules` - List all scheduled tasks
- [ ] `POST /api/schedules` - Create new scheduled task
- [ ] `GET /api/schedules/:id` - Get task details
- [ ] `PUT /api/schedules/:id` - Update task
- [ ] `DELETE /api/schedules/:id` - Delete task
- [ ] `POST /api/schedules/:id/enable` - Enable task
- [ ] `POST /api/schedules/:id/disable` - Disable task
- [ ] `POST /api/schedules/:id/run` - Trigger immediate execution
- [ ] Input validation with proper error messages
- [ ] Return proper HTTP status codes

**Files:**
- `src/genesis/api/schedules.py`

---

#### US-3.2: Schedule History API
**Priority:** Medium | **Estimate:** 1h | **Dependencies:** US-3.1

**As a** user
**I want** to view execution history for scheduled tasks
**So that** I can monitor and debug task runs

**Acceptance Criteria:**
- [ ] `GET /api/schedules/:id/history` - Get execution history
- [ ] Query params: `limit`, `offset`, `status`
- [ ] `GET /api/schedules/:id/history/:history_id` - Get specific run details
- [ ] Return execution time, duration, status, result summary
- [ ] Pagination support

**Files:**
- `src/genesis/api/schedules.py` (extend)

---

### Wave 4: Web UI

#### US-4.1: Schedules List Page
**Priority:** Medium | **Estimate:** 2h | **Dependencies:** US-3.1

**As a** user
**I want** a web page to view all scheduled tasks
**So that** I can see what tasks are scheduled at a glance

**Acceptance Criteria:**
- [ ] Create `src/web/templates/schedules.html`
- [ ] Display table with: name, schedule, status, next run, last run
- [ ] Color-coded status indicators
- [ ] Enable/Disable toggle buttons
- [ ] Delete button with confirmation
- [ ] Run now button
- [ ] Filter by status (enabled/disabled)
- [ ] Sort by name, next_run_at

**Files:**
- `src/web/templates/schedules.html`
- `src/web/schedules.py` (routes)

---

#### US-4.2: Schedule Create/Edit Form
**Priority:** Medium | **Estimate:** 2h | **Dependencies:** US-4.1

**As a** user
**I want** a form to create and edit scheduled tasks
**So that** I can configure task schedules easily

**Acceptance Criteria:**
- [ ] Create `src/web/templates/schedule_form.html`
- [ ] Fields: name, description, schedule_type
- [ ] Cron expression input with helper text
- [ ] Interval input (minutes/hours/days)
- [ ] One-time datetime picker
- [ ] Task type selector (agent/shell/tool)
- [ ] Task payload editor (JSON or form builder)
- [ ] Notification settings
- [ ] Validate form before submission
- [ ] Show cron expression preview (next 5 runs)

**Files:**
- `src/web/templates/schedule_form.html`
- `src/web/schedules.py` (extend)

---

#### US-4.3: Schedule Detail Page
**Priority:** Low | **Estimate:** 1h | **Dependencies:** US-4.1

**As a** user
**I want** a detailed view of a scheduled task
**So that** I can see full configuration and history

**Acceptance Criteria:**
- [ ] Create `src/web/templates/schedule_detail.html`
- [ ] Show all task configuration
- [ ] Show execution history table
- [ ] Show success/failure chart
- [ ] Show average duration
- [ ] Links to edit/delete

**Files:**
- `src/web/templates/schedule_detail.html`

---

### Wave 5: Advanced Features

#### US-5.1: Notification Integration
**Priority:** Medium | **Estimate:** 1h | **Dependencies:** US-2.2

**As a** user
**I want** to receive notifications when scheduled tasks complete
**So that** I'm informed of task results

**Acceptance Criteria:**
- [ ] Integrate with existing Telegram notifier
- [ ] Send notification on task completion (configurable)
- [ ] Send notification on task failure (configurable)
- [ ] Include task name, status, summary in notification
- [ ] Support multiple notification channels

**Files:**
- `src/genesis/scheduler/executor.py` (extend)

---

#### US-5.2: YAML Schedule Loading
**Priority:** Low | **Estimate:** 1h | **Dependencies:** US-3.1

**As a** developer
**I want** to define schedules in a YAML file
**So that** schedules can be version-controlled

**Acceptance Criteria:**
- [ ] Create `config/schedules.yaml` schema
- [ ] Function to load schedules from YAML
- [ ] Sync YAML schedules to database on startup
- [ ] Support create/update from YAML
- [ ] Don't delete schedules not in YAML (flag as external)

**Files:**
- `config/schedules.yaml`
- `src/genesis/scheduler/yaml_loader.py`

---

#### US-5.3: Timezone Support
**Priority:** Low | **Estimate:** 0.5h | **Dependencies:** US-2.1

**As a** user
**I want** to specify timezone for cron schedules
**So that** tasks run at correct local time

**Acceptance Criteria:**
- [ ] Store timezone in scheduled_tasks table
- [ ] Evaluate cron in specified timezone
- [ ] Default to UTC if not specified
- [ ] Web UI timezone selector

**Files:**
- `src/genesis/scheduler/parser.py` (extend)

---

#### US-5.4: Task Retry Logic
**Priority:** Low | **Estimate:** 1h | **Dependencies:** US-2.2

**As a** user
**I want** failed tasks to retry automatically
**So that** transient failures don't cause permanent failures

**Acceptance Criteria:**
- [ ] Add `retry_count` and `max_retries` columns
- [ ] Retry on transient errors (timeout, network)
- [ ] Exponential backoff between retries
- [ ] Don't retry on permanent errors (invalid input)
- [ ] Update history with retry attempts

**Files:**
- `migrations/` (add columns)
- `src/genesis/scheduler/executor.py` (extend)

---

## Progress Tracking

| Wave | Story | Status | Assignee | Started | Completed |
|------|-------|--------|----------|---------|-----------|
| 1 | US-1.1 Database Migration | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 1 | US-1.2 ScheduledTask Model | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 2 | US-2.1 Cron Parser | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 2 | US-2.2 Task Executor | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 2 | US-2.3 Scheduler Daemon | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 2 | US-2.4 Daemon Startup Script | ✅ completed | - | 2026-03-25 | 2026-03-25 |
| 3 | US-3.1 Schedule CRUD API | pending | - | - | - |
| 3 | US-3.2 Schedule History API | pending | - | - | - |
| 4 | US-4.1 Schedules List Page | pending | - | - | - |
| 4 | US-4.2 Schedule Create/Edit Form | pending | - | - | - |
| 4 | US-4.3 Schedule Detail Page | pending | - | - | - |
| 5 | US-5.1 Notification Integration | pending | - | - | - |
| 5 | US-5.2 YAML Schedule Loading | pending | - | - | - |
| 5 | US-5.3 Timezone Support | pending | - | - | - |
| 5 | US-5.4 Task Retry Logic | pending | - | - | - |

## Dependencies Graph

```
US-1.1 (DB Migration)
    └── US-1.2 (Model)
           ├── US-2.1 (Cron Parser)
           │      └── US-2.3 (Daemon)
           └── US-2.2 (Executor)
                  ├── US-2.3 (Daemon)
                  └── US-5.1 (Notifications)
                         
US-1.2 (Model)
    └── US-3.1 (CRUD API)
           ├── US-3.2 (History API)
           ├── US-4.1 (List Page)
           ├── US-4.2 (Form)
           │      └── US-4.3 (Detail Page)
           └── US-5.2 (YAML Loading)

US-2.3 (Daemon)
    └── US-2.4 (Startup Script)
```

## Parallelization Opportunities

**Can run in parallel:**
- Wave 1: US-1.1 and US-1.2 (model can be developed alongside DB design)
- Wave 2: US-2.1 and US-2.2 (parser and executor are independent)
- Wave 3: Can start after Wave 1 complete
- Wave 4: Can start after US-3.1 complete
- Wave 5: US-5.2 and US-5.3 can run in parallel

**Minimum Viable Product (MVP):**
- US-1.1 + US-1.2 + US-2.1 + US-2.2 + US-2.3 + US-3.1
- This gives: database, daemon, and basic API

## Testing Strategy

- **Unit tests:** Parser functions, model validation
- **Integration tests:** API endpoints, executor
- **E2E tests:** Create schedule → wait for execution → verify result

## Notes

- Scheduler daemon should run on Genesis node (not worker)
- Use existing `TaskScheduler` class to submit to Temporal
- Leverage existing notification infrastructure
- Consider using APScheduler as alternative to custom daemon
