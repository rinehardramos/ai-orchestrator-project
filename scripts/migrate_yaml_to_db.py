"""
scripts/migrate_yaml_to_db.py

One-time migration: reads config/tools.yaml and inserts all tool entries
into the Postgres tools/tool_configs/credentials tables.

Run AFTER executing migrations/001_tools_schema.sql:
    psql $DATABASE_URL < migrations/001_tools_schema.sql
    python scripts/migrate_yaml_to_db.py

Environment variables required:
    DATABASE_URL    — postgres connection string
    CONFIG_SECRET_KEY — base64-encoded 32-byte AES key for credential encryption

Usage:
    # Dry run (print what would be inserted, no DB writes)
    python scripts/migrate_yaml_to_db.py --dry-run

    # Live run
    python scripts/migrate_yaml_to_db.py

    # Generate a new secret key for CONFIG_SECRET_KEY
    python scripts/migrate_yaml_to_db.py --gen-key
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys

import yaml

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.plugins.loader import _resolve_env_vars, encrypt_credential

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Keys treated as credentials (encrypted in DB). Everything else goes to tool_configs.
CREDENTIAL_KEYS = {
    "password", "api_key", "auth_token", "secret", "token",
    "private_key", "access_key", "secret_key", "bot_token",
    "account_sid", "smtp_password", "imap_password", "client_secret",
}


async def migrate(dry_run: bool = False) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    secret_key = os.environ.get("CONFIG_SECRET_KEY", "")

    if not database_url:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    if not secret_key and not dry_run:
        log.error("CONFIG_SECRET_KEY not set — run with --gen-key to create one")
        sys.exit(1)

    # Load tools.yaml
    with open("config/tools.yaml") as f:
        raw = yaml.safe_load(f)

    # Resolve env vars so we can see what values are set
    resolved = _resolve_env_vars(raw)
    tools = resolved.get("tools", {})

    log.info(f"Found {len(tools)} tool entries in tools.yaml")

    if dry_run:
        log.info("DRY RUN — no DB writes\n")
        for name, entry in tools.items():
            if not isinstance(entry, dict) or "module" not in entry:
                continue
            config = entry.get("config", {})
            plain_keys = [k for k in config if k not in CREDENTIAL_KEYS]
            cred_keys = [k for k in config if k in CREDENTIAL_KEYS]
            log.info(f"  TOOL: {name}")
            log.info(f"    module:  {entry.get('module')}")
            log.info(f"    enabled: {entry.get('enabled', False)}")
            log.info(f"    node:    {entry.get('node', 'both')}")
            if plain_keys:
                log.info(f"    config:  {plain_keys}")
            if cred_keys:
                log.info(f"    creds:   {cred_keys} (will be encrypted)")
        return

    try:
        import asyncpg
    except ImportError:
        log.error("asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    inserted = 0
    skipped = 0

    try:
        async with conn.transaction():
            for name, entry in tools.items():
                if not isinstance(entry, dict) or "module" not in entry:
                    continue

                # Upsert into tools table
                await conn.execute("""
                    INSERT INTO tools (name, type, module, enabled, listen, node, description)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (name) DO UPDATE SET
                        type        = EXCLUDED.type,
                        module      = EXCLUDED.module,
                        enabled     = EXCLUDED.enabled,
                        listen      = EXCLUDED.listen,
                        node        = EXCLUDED.node,
                        description = EXCLUDED.description,
                        updated_at  = now()
                """,
                    name,
                    entry.get("type", ""),
                    entry.get("module", ""),
                    entry.get("enabled", False),
                    entry.get("listen", False),
                    entry.get("node", "both"),
                    entry.get("description", ""),
                )

                # Insert config key/value pairs
                config = entry.get("config", {})
                for key, value in config.items():
                    str_value = str(value) if not isinstance(value, str) else value

                    if key in CREDENTIAL_KEYS:
                        # Encrypt and store in credentials table
                        encrypted = encrypt_credential(str_value, secret_key)
                        await conn.execute("""
                            INSERT INTO credentials (tool_name, key, value)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (tool_name, key) DO UPDATE
                                SET value = EXCLUDED.value
                        """, name, key, encrypted)
                    else:
                        # Store plaintext in tool_configs table
                        await conn.execute("""
                            INSERT INTO tool_configs (tool_name, key, value)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (tool_name, key) DO UPDATE
                                SET value = EXCLUDED.value
                        """, name, key, str_value)

                log.info(f"Migrated: {name}")
                inserted += 1

    except Exception as e:
        log.error(f"Migration failed: {e}")
        raise
    finally:
        await conn.close()

    log.info(f"\nMigration complete — {inserted} tools inserted, {skipped} skipped")
    log.info("Redis cache will auto-refresh on next load_tools() call")


def generate_key() -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    print(f"\nGenerated CONFIG_SECRET_KEY:\n  {key}")
    print("\nAdd to your .env file:")
    print(f"  CONFIG_SECRET_KEY={key}")
    print("\nAdd to bootstrap.yaml:")
    print("  secret_key: ${CONFIG_SECRET_KEY}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate tools.yaml to Postgres DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be migrated without writing to DB")
    parser.add_argument("--gen-key", action="store_true",
                        help="Generate a new CONFIG_SECRET_KEY and exit")
    args = parser.parse_args()

    if args.gen_key:
        generate_key()
        sys.exit(0)

    asyncio.run(migrate(dry_run=args.dry_run))
