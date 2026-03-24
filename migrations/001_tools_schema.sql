-- migrations/001_tools_schema.sql
--
-- Tool plugin registry schema.
-- Run this once to set up the tools database:
--   psql $DATABASE_URL < migrations/001_tools_schema.sql
--
-- After running, populate with existing tools via:
--   python scripts/migrate_yaml_to_db.py
--
-- The loader reads from these tables (with Redis cache).
-- The HTTP API writes to these tables when tools are registered.

-- ---------------------------------------------------------------------------
-- tools — one row per tool instance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tools (
    name            TEXT PRIMARY KEY,
    -- instance name used as agent function prefix: "gmail_work", "mysql_prod"

    type            TEXT NOT NULL,
    -- category: "chat", "email", "code", "data", "queue", "webhook",
    --           "sms", "media", "cloud", "mcp", "api", "network", "stream"

    module          TEXT NOT NULL,
    -- Python import path: "src.tools_catalog.email.gmail"

    enabled         BOOLEAN NOT NULL DEFAULT false,
    -- false = tool is known but not loaded. Toggle with /tools/{name}/enable

    listen          BOOLEAN NOT NULL DEFAULT false,
    -- true = genesis calls start_listener() at startup (Telegram, http_server, etc.)

    node            TEXT NOT NULL DEFAULT 'both',
    -- "genesis" | "worker" | "both"
    -- Loader skips tools that don't match the current node.

    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- tool_configs — non-sensitive settings for each tool instance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tool_configs (
    tool_name   TEXT NOT NULL REFERENCES tools(name) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT,
    PRIMARY KEY (tool_name, key)
);

-- ---------------------------------------------------------------------------
-- credentials — sensitive values stored encrypted (AES-256-GCM)
-- ---------------------------------------------------------------------------
-- The loader decrypts these using the secret_key from bootstrap.yaml.
-- Use scripts/encrypt_credential.py to encrypt values before inserting.
-- NEVER store plaintext passwords here.
CREATE TABLE IF NOT EXISTS credentials (
    tool_name   TEXT NOT NULL REFERENCES tools(name) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    -- Format: nonce(12 bytes) || ciphertext || GCM-tag(16 bytes)
    -- Encrypted with AES-256-GCM using CONFIG_SECRET_KEY from bootstrap.yaml
    value       BYTEA NOT NULL,
    PRIMARY KEY (tool_name, key)
);

-- ---------------------------------------------------------------------------
-- Trigger to auto-update updated_at on tools table
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tools_updated_at ON tools;
CREATE TRIGGER tools_updated_at
    BEFORE UPDATE ON tools
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ---------------------------------------------------------------------------
-- Seed data — initial tool instances matching config/tools.yaml
-- Disabled by default. Enable after the tool modules are implemented.
-- ---------------------------------------------------------------------------
INSERT INTO tools (name, type, module, enabled, listen, node, description)
VALUES
    ('http_server', 'api',     'src.tools_catalog.api.http_server',       false, true,  'genesis', 'Universal HTTP+SSE source for TUIs, scripts, and curl'),
    ('telegram',    'chat',    'src.tools_catalog.chat.telegram',          false, true,  'both',    'Send and receive messages via Telegram'),
    ('shell',       'code',    'src.tools_catalog.code.shell',             false, false, 'worker',  'Execute shell commands'),
    ('filesystem',  'code',    'src.tools_catalog.code.filesystem',        false, false, 'worker',  'Read, write, and manage files'),
    ('web',         'code',    'src.tools_catalog.code.web',               false, false, 'worker',  'Web search and URL fetching'),
    ('git',         'code',    'src.tools_catalog.code.git',               false, false, 'worker',  'Git operations: clone, commit, push, branch'),
    ('image',       'media',   'src.tools_catalog.media.image',            false, false, 'worker',  'Generate images using AI models'),
    ('http_client', 'webhook', 'src.tools_catalog.webhook.http_client',    false, false, 'worker',  'Make HTTP requests (GET, POST, PUT, DELETE)'),
    ('google_drive','mcp',     'src.plugins.mcp_bridge',                   false, false, 'worker',  'Google Drive via MCP: list, read, write, search files')
ON CONFLICT (name) DO NOTHING;

-- Seed tool_configs for non-sensitive defaults
INSERT INTO tool_configs (tool_name, key, value)
VALUES
    ('http_server', 'host', '127.0.0.1'),
    ('http_server', 'port', '8000'),
    ('shell',       'timeout_seconds', '120'),
    ('google_drive','transport', 'stdio'),
    ('google_drive','command', 'npx -y @modelcontextprotocol/server-gdrive')
ON CONFLICT (tool_name, key) DO NOTHING;
