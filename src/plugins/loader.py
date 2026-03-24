"""
Tool Loader.

Loads tool instances from the database (primary) or tools.yaml (fallback).
Populates the global registry.

Entrypoints:
    await load_tools("config/bootstrap.yaml", node="worker")
    await load_tools("config/bootstrap.yaml", node="genesis")

The node parameter filters which tools to load:
    node="worker"  → loads tools with node="worker" or node="both"
    node="genesis" → loads tools with node="genesis" or node="both"

Each tool module must export:
    tool_class = MyToolClass   (the class, not an instance)
"""

import importlib
import json
import logging
import os
import re
from typing import Optional

import yaml

# Load .env file before any other processing
from dotenv import load_dotenv
load_dotenv()

from src.plugins.registry import registry

log = logging.getLogger(__name__)


def load_tools_sync(bootstrap_path: str = "config/bootstrap.yaml",
                    node: str = "worker") -> None:
    """
    Synchronous version of load_tools for use in sync contexts.
    Loads from database if available, falls back to YAML.
    """
    bootstrap = _load_bootstrap(bootstrap_path)
    db_url = bootstrap.get("database_url", "")
    secret_key = bootstrap.get("secret_key", "")
    
    tools_config = {}
    
    # Try to load from DB first
    if db_url:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("SELECT name, type, module, enabled, listen, node FROM tools WHERE enabled = true")
            rows = cur.fetchall()
            for row in rows:
                name, typ, module, enabled, listen, node_val = row
                cur.execute("SELECT key, value FROM tool_configs WHERE tool_name = %s", (name,))
                config = {r[0]: r[1] for r in cur.fetchall()}
                
                if secret_key:
                    cur.execute("SELECT key, value FROM credentials WHERE tool_name = %s", (name,))
                    for r in cur.fetchall():
                        config[r[0]] = _decrypt(r[1], secret_key)
                
                tools_config[name] = {
                    "type": typ,
                    "module": module,
                    "enabled": enabled,
                    "listen": listen,
                    "node": node_val,
                    "config": config
                }
            conn.close()
            log.info(f"Loaded {len(tools_config)} tools from DB (sync)")
        except Exception as e:
            log.warning(f"DB load failed ({e}), falling back to YAML")
            tools_config = _load_from_yaml("config/tools.yaml")
    else:
        tools_config = _load_from_yaml("config/tools.yaml")
    
    loaded = 0
    skipped = 0
    for name, entry in tools_config.items():
        if not isinstance(entry, dict) or "module" not in entry:
            continue
        if not entry.get("enabled", False):
            continue
        tool_node = entry.get("node", "both")
        if tool_node != "both" and tool_node != node:
            continue
        
        try:
            module = importlib.import_module(entry["module"])
            tool_class = getattr(module, "tool_class", None)
            if tool_class is None:
                log.warning(f"Tool {name}: module {entry['module']} has no 'tool_class' export")
                skipped += 1
                continue
            
            instance = tool_class()
            instance.name = name
            instance.listen = entry.get("listen", instance.listen)
            instance.node = entry.get("node", instance.node)
            instance.initialize(entry.get("config", {}))
            registry.register(instance)
            loaded += 1
        except Exception as e:
            log.warning(f"Failed to load tool '{name}': {e}")
            skipped += 1
    
    log.info(f"Sync loader complete — {loaded} loaded, {skipped} skipped (node={node})")


async def load_tools(bootstrap_path: str = "config/bootstrap.yaml",
                     node: str = "worker") -> None:
    """
    Load all enabled tools into the global registry.

    Tries the database first. Falls back to config/tools.yaml if the DB
    is unavailable (e.g. first boot, dev environment, DB not yet set up).

    bootstrap_path: path to bootstrap.yaml with DB/Redis connection info
    node:           "worker" or "genesis" — only loads tools for this node
    """
    bootstrap = _load_bootstrap(bootstrap_path)
    tools_config = await _load_tool_configs(bootstrap)

    loaded = 0
    skipped = 0
    for name, entry in tools_config.items():
        # Skip internal config entries (e.g. tool_builder)
        if not isinstance(entry, dict) or "module" not in entry:
            continue

        # Skip disabled tools
        if not entry.get("enabled", False):
            continue

        # Filter by node
        tool_node = entry.get("node", "both")
        if tool_node != "both" and tool_node != node:
            continue

        try:
            module = importlib.import_module(entry["module"])
            tool_class = getattr(module, "tool_class", None)
            if tool_class is None:
                log.warning(f"Tool {name}: module {entry['module']} has no "
                            f"'tool_class' export — skipping")
                skipped += 1
                continue

            instance = tool_class()
            instance.name = name  # override with instance name from config
            instance.listen = entry.get("listen", instance.listen)
            instance.node = entry.get("node", instance.node)
            instance.initialize(entry.get("config", {}))
            registry.register(instance)
            loaded += 1
        except Exception as e:
            log.warning(f"Failed to load tool '{name}' "
                        f"({entry.get('module', '?')}): {e}")
            skipped += 1

    log.info(f"Tool loader complete — {loaded} loaded, {skipped} skipped "
             f"(node={node})")


# -----------------------------------------------------------------------------
# Bootstrap loading
# -----------------------------------------------------------------------------

def _load_bootstrap(path: str) -> dict:
    """Load bootstrap.yaml and resolve ${ENV_VAR} references."""
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        return _resolve_env_vars(raw)
    except FileNotFoundError:
        log.warning(f"Bootstrap file not found: {path} — using empty config")
        return {}


# -----------------------------------------------------------------------------
# Tool config loading — DB primary, YAML fallback
# -----------------------------------------------------------------------------

async def _load_tool_configs(bootstrap: dict) -> dict:
    """Try DB → YAML fallback. Returns {name: {module, type, enabled, config}}."""
    db_url = bootstrap.get("database_url", "")
    if db_url:
        try:
            return await _load_from_db(db_url, bootstrap.get("secret_key", ""))
        except Exception as e:
            log.warning(f"DB unavailable ({e}) — falling back to tools.yaml")

    return _load_from_yaml()


async def _load_from_db(database_url: str, secret_key: str) -> dict:
    """
    Load tool configs from Postgres.
    Caches results in Redis with TTL=60s for fast subsequent loads.

    Schema:
        tools(name, type, module, enabled, listen, node)
        tool_configs(tool_name, key, value)
        credentials(tool_name, key, value BYTEA)  -- AES-256-GCM encrypted
    """
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError(
            "asyncpg not installed. Run: pip install asyncpg"
        )

    # Check Redis cache first
    cached = await _redis_get("tools:list:all")
    if cached:
        log.debug("Tool configs loaded from Redis cache")
        return json.loads(cached)

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            "SELECT name, type, module, enabled, listen, node, description "
            "FROM tools ORDER BY name"
        )
        result = {}
        for row in rows:
            name = row["name"]
            # Load non-sensitive config
            config_rows = await conn.fetch(
                "SELECT key, value FROM tool_configs WHERE tool_name=$1", name
            )
            config = {r["key"]: r["value"] for r in config_rows}

            # Load and decrypt credentials
            if secret_key:
                cred_rows = await conn.fetch(
                    "SELECT key, value FROM credentials WHERE tool_name=$1", name
                )
                for r in cred_rows:
                    config[r["key"]] = _decrypt(r["value"], secret_key)

            result[name] = {
                "type":        row["type"],
                "module":      row["module"],
                "enabled":     row["enabled"],
                "listen":      row["listen"],
                "node":        row["node"] or "both",
                "description": row["description"] or "",
                "config":      config,
            }

        # Cache in Redis for 60 seconds
        await _redis_set("tools:list:all", json.dumps(result), ttl=60)
        log.info(f"Loaded {len(result)} tool configs from DB")
        return result
    finally:
        await conn.close()


def _load_from_yaml(path: str = "config/tools.yaml") -> dict:
    """Load tool configs from YAML file. Resolves ${ENV_VAR} references."""
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        resolved = _resolve_env_vars(raw)
        tools = resolved.get("tools", {})
        log.info(f"Loaded {len(tools)} tool configs from {path}")
        return tools
    except FileNotFoundError:
        log.warning(f"tools.yaml not found at {path} — no tools loaded")
        return {}


# -----------------------------------------------------------------------------
# Redis cache helpers
# -----------------------------------------------------------------------------

async def _redis_get(key: str) -> Optional[str]:
    """Get a value from Redis. Returns None if unavailable."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(_get_redis_url())
        value = await r.get(key)
        await r.aclose()
        return value.decode() if value else None
    except Exception:
        return None


async def _redis_set(key: str, value: str, ttl: int = 60) -> None:
    """Set a value in Redis with TTL. Silently ignores failures."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(_get_redis_url())
        await r.setex(key, ttl, value)
        await r.aclose()
    except Exception:
        pass


async def invalidate_tool_cache(tool_name: str = None) -> None:
    """
    Invalidate Redis tool cache after a DB change.
    Call this after registering, enabling, or disabling a tool.
    If tool_name is given, also invalidate that tool's individual config cache.
    """
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(_get_redis_url())
        await r.delete("tools:list:all")
        if tool_name:
            await r.delete(f"tools:config:{tool_name}")
        await r.aclose()
    except Exception as e:
        log.warning(f"Could not invalidate tool cache: {e}")


def _get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://192.168.100.249:6379")


# -----------------------------------------------------------------------------
# Credential encryption
# -----------------------------------------------------------------------------

def _decrypt(encrypted_bytes: bytes, secret_key: str) -> str:
    """
    Decrypt a credential value using AES-256-GCM via the cryptography library.
    secret_key must be a 32-byte base64-encoded string (set in bootstrap.yaml).

    Format of encrypted_bytes: nonce(12) + ciphertext + tag(16)
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64
        key_bytes = base64.b64decode(secret_key)[:32]
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        aesgcm = AESGCM(key_bytes)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
    except ImportError:
        raise RuntimeError("cryptography not installed. Run: pip install cryptography")
    except Exception as e:
        log.error(f"Credential decryption failed: {e}")
        return ""


def encrypt_credential(plaintext: str, secret_key: str) -> bytes:
    """
    Encrypt a credential for storage in the credentials table.
    Returns bytes to store in the BYTEA column.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64
        import os as _os
        key_bytes = base64.b64decode(secret_key)[:32]
        nonce = _os.urandom(12)
        aesgcm = AESGCM(key_bytes)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext
    except ImportError:
        raise RuntimeError("cryptography not installed. Run: pip install cryptography")


# -----------------------------------------------------------------------------
# Env var resolution
# -----------------------------------------------------------------------------

def _resolve_env_vars(obj):
    """
    Recursively replace ${VAR_NAME} with os.environ[VAR_NAME] in any dict/list/str.
    If the env var is not set, the placeholder is left as-is and a warning is logged.
    """
    if isinstance(obj, str):
        def replacer(match):
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                log.warning(f"Env var ${{{var}}} not set in environment")
                return match.group(0)  # leave placeholder
            return val
        return re.sub(r'\$\{(\w+)\}', replacer, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj
