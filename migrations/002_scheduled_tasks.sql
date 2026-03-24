-- =============================================================================
-- Migration: 002_scheduled_tasks.sql
-- Description: Add scheduled tasks (cron-like) feature
-- Version: 1.0
-- Created: 2026-03-25
-- =============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Table: scheduled_tasks
-- Stores recurring and one-time scheduled tasks
-- =============================================================================
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    -- Identity
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Schedule configuration
    schedule_type VARCHAR(20) NOT NULL CHECK (schedule_type IN ('cron', 'interval', 'once')),
    cron_expression VARCHAR(100),
    interval_seconds INTEGER,
    scheduled_for TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- Task configuration
    task_type VARCHAR(50) NOT NULL CHECK (task_type IN ('agent', 'shell', 'tool', 'workflow')),
    task_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Execution state
    enabled BOOLEAN DEFAULT true,
    status VARCHAR(20) DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'paused', 'disabled', 'error')),
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    last_run_status VARCHAR(20),
    last_run_task_id VARCHAR(100),
    last_run_duration_seconds INTEGER,
    last_error TEXT,
    
    -- Counters & limits
    run_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    max_failures INTEGER DEFAULT 3,
    max_runs INTEGER,
    timeout_seconds INTEGER DEFAULT 300,
    
    -- Notification settings
    notify_on_success BOOLEAN DEFAULT false,
    notify_on_failure BOOLEAN DEFAULT true,
    notify_on_start BOOLEAN DEFAULT false,
    notification_channel VARCHAR(50) DEFAULT 'telegram',
    notification_recipients JSONB DEFAULT '[]'::jsonb,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    tags JSONB DEFAULT '[]'::jsonb,
    
    -- Constraints
    CONSTRAINT valid_cron CHECK (
        (schedule_type = 'cron' AND cron_expression IS NOT NULL) OR
        (schedule_type = 'interval' AND interval_seconds IS NOT NULL AND interval_seconds > 0) OR
        (schedule_type = 'once' AND scheduled_for IS NOT NULL)
    )
);

-- =============================================================================
-- Table: scheduled_task_history
-- Tracks execution history for each scheduled task
-- =============================================================================
CREATE TABLE IF NOT EXISTS scheduled_task_history (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    scheduled_task_id INTEGER NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    
    -- Execution details
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    
    -- Task reference
    temporal_task_id VARCHAR(100),
    temporal_workflow_id VARCHAR(100),
    
    -- Results
    status VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed', 'timeout', 'cancelled')),
    result_summary TEXT,
    error_message TEXT,
    error_traceback TEXT,
    
    -- Metrics
    cost_usd DECIMAL(10, 6),
    tool_call_count INTEGER,
    
    -- Full result
    full_result JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- Indexes for performance
-- =============================================================================

CREATE INDEX idx_scheduled_tasks_due ON scheduled_tasks(enabled, status, next_run_at)
    WHERE enabled = true AND status IN ('idle', 'running');

CREATE INDEX idx_scheduled_tasks_name ON scheduled_tasks(name);

CREATE INDEX idx_scheduled_tasks_type ON scheduled_tasks(task_type);

CREATE INDEX idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at)
    WHERE enabled = true;

CREATE INDEX idx_scheduled_task_history_task_id ON scheduled_task_history(scheduled_task_id);

CREATE INDEX idx_scheduled_task_history_started_at ON scheduled_task_history(started_at DESC);

CREATE INDEX idx_scheduled_task_history_status ON scheduled_task_history(status);

-- =============================================================================
-- Trigger: Auto-update updated_at timestamp
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_scheduled_tasks_updated_at ON scheduled_tasks;
CREATE TRIGGER update_scheduled_tasks_updated_at
    BEFORE UPDATE ON scheduled_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Trigger: Auto-calculate next_run_at on insert/update
-- =============================================================================
CREATE OR REPLACE FUNCTION calculate_next_run_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.schedule_type = 'interval' AND NEW.interval_seconds IS NOT NULL THEN
        IF NEW.last_run_at IS NULL THEN
            NEW.next_run_at = NOW();
        ELSE
            NEW.next_run_at = NEW.last_run_at + (NEW.interval_seconds || ' seconds')::interval;
        END IF;
    ELSIF NEW.schedule_type = 'once' AND NEW.scheduled_for IS NOT NULL THEN
        NEW.next_run_at = NEW.scheduled_for;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS calculate_next_run_at_trigger ON scheduled_tasks;
CREATE TRIGGER calculate_next_run_at_trigger
    BEFORE INSERT OR UPDATE ON scheduled_tasks
    FOR EACH ROW
    EXECUTE FUNCTION calculate_next_run_at();

-- =============================================================================
-- Grant permissions
-- =============================================================================
GRANT ALL PRIVILEGES ON TABLE scheduled_tasks TO temporal;
GRANT ALL PRIVILEGES ON TABLE scheduled_task_history TO temporal;
GRANT ALL PRIVILEGES ON SEQUENCE scheduled_tasks_id_seq TO temporal;
GRANT ALL PRIVILEGES ON SEQUENCE scheduled_task_history_id_seq TO temporal;

-- =============================================================================
-- Migration complete
-- =============================================================================
