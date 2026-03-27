-- migrations/006_config_versioning.sql
--
-- Config versioning system for automatic worker reload.
-- Workers poll config_version to detect changes and reload their cached config.
--
-- UP: Creates config version tracking and triggers for automatic version bumping
-- DOWN: Removes config versioning (rollback)

-- ============================================================================
-- UP
-- ============================================================================

-- Initialize config_version if not exists
INSERT INTO system_state (key, value) 
VALUES ('config_version', '0')
ON CONFLICT (key) DO NOTHING;

-- Create function to bump config version atomically
CREATE OR REPLACE FUNCTION bump_config_version()
RETURNS INTEGER AS $$
DECLARE
    new_version INTEGER;
BEGIN
    UPDATE system_state 
    SET value = (CAST(COALESCE(value, '0') AS INTEGER) + 1)::text,
        updated_at = now()
    WHERE key = 'config_version'
    RETURNING CAST(value AS INTEGER) INTO new_version;
    
    RETURN new_version;
END;
$$ LANGUAGE plpgsql;

-- Create trigger function to auto-bump version on app_config changes
CREATE OR REPLACE FUNCTION auto_bump_config_version()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM bump_config_version();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to app_config table
DROP TRIGGER IF EXISTS app_config_version_trigger ON app_config;
CREATE TRIGGER app_config_version_trigger
    AFTER INSERT OR UPDATE OR DELETE ON app_config
    FOR EACH STATEMENT EXECUTE FUNCTION auto_bump_config_version();

-- Attach trigger to tools table for tool changes
DROP TRIGGER IF EXISTS tools_config_version_trigger ON tools;
CREATE TRIGGER tools_config_version_trigger
    AFTER INSERT OR UPDATE OR DELETE ON tools
    FOR EACH STATEMENT EXECUTE FUNCTION auto_bump_config_version();

-- Create a table to track config change history (optional, for debugging)
CREATE TABLE IF NOT EXISTS config_change_log (
    id SERIAL PRIMARY KEY,
    config_version INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    table_name TEXT,
    record_identifier TEXT,
    changed_by TEXT DEFAULT 'system',
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create index for fast version queries
CREATE INDEX IF NOT EXISTS idx_config_change_log_version 
ON config_change_log(config_version DESC);

-- ============================================================================
-- DOWN (Rollback)
-- ============================================================================
-- 
-- To rollback this migration, run:
--
-- DROP TRIGGER IF EXISTS tools_config_version_trigger ON tools;
-- DROP TRIGGER IF EXISTS app_config_version_trigger ON app_config;
-- DROP FUNCTION IF EXISTS auto_bump_config_version();
-- DROP FUNCTION IF EXISTS bump_config_version();
-- DROP TABLE IF EXISTS config_change_log;
-- DELETE FROM system_state WHERE key = 'config_version';
