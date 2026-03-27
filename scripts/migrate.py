#!/usr/bin/env python3
"""
Master migration script for AI Orchestrator.

Runs all database migrations in order and seeds initial configuration.

Usage:
    python scripts/migrate.py
    python scripts/migrate.py --dry-run
    python scripts/migrate.py --reset   # DANGER: Drops all tables first
"""

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATION_FILES = [
    "001_tools_schema.sql",
    "002_scheduled_tasks.sql",
    "003_app_config.sql",
    "004_defaults.sql",
    "005_spreadsheets.sql",
    "006_config_versioning.sql",
]

DEFAULT_TOOLS = [
    {"name": "http_server", "type": "api", "module": "src.tools_catalog.api.http_server", "enabled": True, "listen": True, "node": "genesis", "description": "Universal HTTP+SSE source for TUIs, scripts, and curl"},
    {"name": "telegram", "type": "chat", "module": "src.tools_catalog.chat.telegram", "enabled": True, "listen": True, "node": "both", "description": "Send and receive messages via Telegram"},
    {"name": "shell", "type": "code", "module": "src.tools_catalog.code.shell", "enabled": True, "listen": False, "node": "worker", "description": "Execute shell commands"},
    {"name": "filesystem", "type": "code", "module": "src.tools_catalog.code.filesystem", "enabled": True, "listen": False, "node": "worker", "description": "Read, write, and manage files"},
    {"name": "web", "type": "code", "module": "src.tools_catalog.code.web", "enabled": True, "listen": False, "node": "worker", "description": "Web search and URL fetching"},
    {"name": "git", "type": "code", "module": "src.tools_catalog.code.git", "enabled": True, "listen": False, "node": "worker", "description": "Git operations: clone, commit, push, branch"},
    {"name": "image", "type": "media", "module": "src.tools_catalog.media.image", "enabled": True, "listen": False, "node": "worker", "description": "Generate images using AI models"},
    {"name": "transcribe_audio", "type": "media", "module": "src.tools_catalog.media.audio", "enabled": True, "listen": False, "node": "worker", "description": "Transcribe audio files"},
    {"name": "analyze_image", "type": "media", "module": "src.tools_catalog.media.vision", "enabled": True, "listen": False, "node": "worker", "description": "Analyze images with vision models"},
    {"name": "http_client", "type": "webhook", "module": "src.tools_catalog.webhook.http_client", "enabled": True, "listen": False, "node": "worker", "description": "Make HTTP requests (GET, POST, PUT, DELETE)"},
    {"name": "google_drive", "type": "mcp", "module": "src.plugins.mcp_bridge", "enabled": False, "listen": False, "node": "worker", "description": "Google Drive via MCP: list, read, write, search files"},
    {"name": "gmail", "type": "email", "module": "src.tools_catalog.email.gmail", "enabled": True, "listen": False, "node": "worker", "description": "Gmail IMAP/SMTP integration"},
    {"name": "knowledge", "type": "data", "module": "src.tools_catalog.data.knowledge", "enabled": True, "listen": False, "node": "both", "description": "Ingest and query documents for knowledge retrieval"},
    {"name": "spreadsheet_query", "type": "data", "module": "src.tools_catalog.data.spreadsheet", "enabled": True, "listen": False, "node": "worker", "description": "Query and analyze spreadsheet data"},
]

DEFAULT_TOOL_CONFIGS = [
    ("http_server", "host", "127.0.0.1"),
    ("http_server", "port", "8000"),
    ("shell", "timeout_seconds", "120"),
    ("google_drive", "transport", "stdio"),
    ("google_drive", "command", "npx -y @modelcontextprotocol/server-gdrive"),
    ("gmail", "imap_host", "imap.gmail.com"),
    ("gmail", "imap_port", "993"),
    ("gmail", "smtp_host", "smtp.gmail.com"),
    ("gmail", "smtp_port", "587"),
    ("gmail", "encryption", "tls"),
]


def get_database_url() -> str:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set")
        log.error("Set in .env file:")
        log.error("  DATABASE_URL=postgres://user:pass@host:5432/dbname")
        sys.exit(1)
    return db_url


def seed_tools(cur, dry_run: bool = False) -> None:
    if dry_run:
        log.info(f"  [DRY RUN] Would seed {len(DEFAULT_TOOLS)} tools")
        return
    
    for tool in DEFAULT_TOOLS:
        try:
            cur.execute("""
                INSERT INTO tools (name, type, module, enabled, listen, node, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    type = EXCLUDED.type,
                    module = EXCLUDED.module,
                    enabled = EXCLUDED.enabled,
                    listen = EXCLUDED.listen,
                    node = EXCLUDED.node,
                    description = EXCLUDED.description,
                    updated_at = now()
            """, (tool["name"], tool["type"], tool["module"], tool["enabled"], tool["listen"], tool["node"], tool["description"]))
            log.info(f"  Seeded tool: {tool['name']}")
        except Exception as e:
            log.error(f"  Failed to seed tool {tool['name']}: {e}")
    
    for tool_name, key, value in DEFAULT_TOOL_CONFIGS:
        try:
            cur.execute("""
                INSERT INTO tool_configs (tool_name, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (tool_name, key) DO UPDATE SET value = EXCLUDED.value
            """, (tool_name, key, value))
        except Exception as e:
            log.error(f"  Failed to seed config {tool_name}.{key}: {e}")


def get_rollback_sql(migration_file: str) -> str:
    """Extract rollback SQL from migration file (between DOWN comments)."""
    path = MIGRATIONS_DIR / migration_file
    if not path.exists():
        return None
    
    with open(path, "r") as f:
        content = f.read()
    
    # Find rollback section between DOWN and end of file or next marker
    import re
    match = re.search(r'--\s*DOWN.*?\n(.+?)(?=\n--\s*UP|\Z)', content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Alternative: look for rollback comment section
    lines = content.split('\n')
    in_rollback = False
    rollback_lines = []
    for line in lines:
        if '-- DOWN' in line or '-- Rollback' in line:
            in_rollback = True
            continue
        if in_rollback and line.startswith('--'):
            continue
        if in_rollback:
            rollback_lines.append(line)
    
    return '\n'.join(rollback_lines).strip() if rollback_lines else None


def rollback_migration(migration_file: str, dry_run: bool = False) -> bool:
    """Rollback a specific migration."""
    rollback_sql = get_rollback_sql(migration_file)
    if not rollback_sql:
        log.warning(f"No rollback SQL found in {migration_file}")
        return False
    
    log.info(f"Rolling back: {migration_file}")
    log.info(f"Rollback SQL:\n{rollback_sql[:500]}...")
    
    if dry_run:
        log.info("  [DRY RUN] Would execute rollback")
        return True
    
    try:
        import psycopg2
        db_url = get_database_url()
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        # Execute rollback statements
        for statement in rollback_sql.split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    cur.execute(statement)
                except Exception as e:
                    log.warning(f"  Statement failed (may be expected): {e}")
        
        conn.close()
        log.info(f"  Rollback complete")
        return True
    except Exception as e:
        log.error(f"  Rollback failed: {e}")
        return False


def run_migrations(dry_run: bool = False, reset: bool = False, rollback: str = None) -> None:
    try:
        import psycopg2
    except ImportError:
        log.error("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    db_url = get_database_url()
    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    try:
        cur = conn.cursor()

        if reset:
            log.warning("RESETTING DATABASE - Dropping all tables...")
            tables = [
                "scheduled_task_history",
                "scheduled_tasks",
                "credentials",
                "tool_configs",
                "tools",
                "app_config",
                "system_state",
            ]
            for table in tables:
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            log.info("All tables dropped")

        for filename in MIGRATION_FILES:
            path = MIGRATIONS_DIR / filename
            if not path.exists():
                log.error(f"Migration file not found: {path}")
                sys.exit(1)

            log.info(f"Running: {filename}")
            with open(path, "r") as f:
                sql = f.read()

            if dry_run:
                log.info(f"  [DRY RUN] Would execute {len(sql)} bytes of SQL")
            else:
                try:
                    cur.execute(sql)
                    log.info(f"  OK")
                except Exception as e:
                    log.error(f"  FAILED: {e}")
                    sys.exit(1)

        if not dry_run:
            log.info("Seeding tools...")
            seed_tools(cur, dry_run=False)
            
            cur.execute(
                "INSERT INTO system_state (key, value) VALUES ('setup_complete', 'true') "
                "ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = now()"
            )
            log.info("Setup marked as complete")

            cur.execute("SELECT COUNT(*) FROM tools")
            tool_count = cur.fetchone()[0]
            log.info(f"Tools in database: {tool_count}")

            cur.execute("SELECT COUNT(*) FROM app_config")
            config_count = cur.fetchone()[0]
            log.info(f"Config entries: {config_count}")

        log.info("Migration complete!")

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--reset", action="store_true", help="Drop all tables first (DANGER)")
    parser.add_argument("--rollback", type=str, help="Rollback a specific migration file (e.g., 006_config_versioning.sql)")
    args = parser.parse_args()

    if args.reset and not args.dry_run:
        confirm = input("This will DELETE ALL DATA. Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    if args.rollback:
        rollback_migration(args.rollback, dry_run=args.dry_run)
    else:
        run_migrations(dry_run=args.dry_run, reset=args.reset)


if __name__ == "__main__":
    main()
