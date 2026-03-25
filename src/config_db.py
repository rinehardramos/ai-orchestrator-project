"""
Database-only configuration loader.

NO YAML fallback. If DB is not configured, system fails with clear error.
"""

import os
import sys
import logging
from typing import Any, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

log = logging.getLogger(__name__)


class ConfigLoader:
    """Load all config from database. Fail if not configured."""
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL not set. Required for startup.\n"
                "Set in .env file:\n"
                "  DATABASE_URL=postgres://user:pass@host:5432/db"
            )
        
        if not psycopg2:
            raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")
        
        self._conn = None
        self._cache: dict[str, Any] = {}
    
    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        return self._conn
    
    def validate_setup(self) -> bool:
        """Check if system has been properly set up."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # Check setup_complete flag
            cur.execute("SELECT value FROM system_state WHERE key = 'setup_complete'")
            row = cur.fetchone()
            if not row or row[0] != 'true':
                return False
            
            return True
        except Exception:
            return False
    
    def get_missing_config(self) -> list[str]:
        """Return list of missing required config items."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            missing = []
            
            # Check required tables
            checks = [
                ("tools", "SELECT COUNT(*) FROM tools WHERE enabled = true"),
                ("profiles config", "SELECT COUNT(*) FROM app_config WHERE namespace = 'profiles'"),
                ("jobs config", "SELECT COUNT(*) FROM app_config WHERE namespace = 'jobs'"),
            ]
            
            for name, query in checks:
                cur.execute(query)
                count = cur.fetchone()[0]
                if count == 0:
                    missing.append(name)
            
            return missing
        except Exception as e:
            return [f"Connection error: {e}"]
    
    def load_namespace(self, namespace: str) -> dict[str, Any]:
        """Load all config for a namespace from app_config."""
        if namespace in self._cache:
            return self._cache[namespace]
        
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute(
            "SELECT key, value FROM app_config WHERE namespace = %s",
            (namespace,)
        )
        
        result = {}
        for row in cur.fetchall():
            result[row['key']] = row['value']
        
        self._cache[namespace] = result
        return result
    
    def load_all_namespaces(self) -> dict[str, Any]:
        """Load all config for all namespaces from app_config."""
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT namespace, key, value FROM app_config")
        
        result = {}
        for row in cur.fetchall():
            ns = row['namespace']
            if ns not in result:
                result[ns] = {}
            result[ns][row['key']] = row['value']
        
        return result
    
    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """Get a single config value."""
        ns = self.load_namespace(namespace)
        return ns.get(key, default)
    
    def get_profiles(self) -> dict:
        """Load model routing profiles."""
        return self.load_namespace('profiles')
    
    def get_jobs_config(self) -> dict:
        """Load agent job defaults."""
        return self.load_namespace('jobs')
    
    def get_specializations(self) -> dict:
        """Load specializations from app_config."""
        ns = self.load_namespace('specializations')
        if not ns:
            return {
                "general": {"allowed_tools": ["shell", "filesystem", "web"]}
            }
        return ns
    
    def mark_setup_complete(self) -> None:
        """Mark setup as complete."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO system_state (key, value) VALUES ('setup_complete', 'true') "
            "ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = now()"
        )
        conn.commit()
        log.info("Setup marked as complete")


# Global instance
_loader: Optional[ConfigLoader] = None


def get_loader() -> ConfigLoader:
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader


def load_settings() -> dict:
    """
    Main entry point for loading settings.
    Fails if DB is not configured.
    """
    loader = get_loader()
    
    # Validate setup
    if not loader.validate_setup():
        missing = loader.get_missing_config()
        print("❌ System not configured. Missing:")
        for m in missing:
            print(f"   - {m}")
        print("\nRun setup:")
        print("   python scripts/migrate_yaml_to_db.py")
        print("   python scripts/seed_noncritical_config.py")
        print("   python scripts/complete_setup.py")
        sys.exit(1)
    
    # Load all config
    return {
        "profiles": loader.get_profiles(),
        "jobs": loader.get_jobs_config(),
        "specializations": loader.get_specializations(),
    }
