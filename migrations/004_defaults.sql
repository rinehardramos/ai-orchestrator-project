-- migrations/004_defaults.sql
--
-- Seed default runtime configuration.
-- These defaults ensure the system starts even if the DB is unconfigured.

INSERT INTO app_config (namespace, key, value) VALUES
('profiles', 'default_model', '"gemini/gemini-2.0-flash"'),
('profiles', 'fallback_model', '"openai/gpt-4o-mini"'),
('profiles', 'max_cost_usd', '0.50'),
('jobs', 'max_tool_calls', '50'),
('jobs', 'activity_timeout_minutes', '30')
ON CONFLICT (namespace, key) DO NOTHING;
