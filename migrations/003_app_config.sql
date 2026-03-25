-- migrations/003_app_config.sql
--
-- Store non-critical runtime configuration in Postgres so operators can
-- manage it via GUI/TUI/CLI instead of editing multiple YAML files by hand.

CREATE TABLE IF NOT EXISTS app_config (
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, key)
);

-- Track setup progress
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO system_state (key, value) 
VALUES ('setup_complete', 'false')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION update_app_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS app_config_updated_at ON app_config;
CREATE TRIGGER app_config_updated_at
    BEFORE UPDATE ON app_config
    FOR EACH ROW EXECUTE FUNCTION update_app_config_updated_at();
