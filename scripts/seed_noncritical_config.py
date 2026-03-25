"""
Seed non-critical YAML configuration into Postgres app_config.

This script is intended for first boot (or refresh) on single-machine setups.
Critical connectivity values still come from per-role .env files.

Usage:
  python scripts/seed_noncritical_config.py --dry-run
  python scripts/seed_noncritical_config.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


SOURCE_FILES: dict[str, str] = {
    "profiles": "config/profiles.yaml",
    "jobs": "config/jobs.yaml",
    "media": "config/media.yaml",
    "cluster_nodes": "config/cluster_nodes.yaml",
    "schedules": "config/schedules.yaml",
    "specializations": "config/profiles.yaml",  # Extract specializations section
}


def _flatten_document(doc: object) -> dict[str, object]:
    if isinstance(doc, dict):
        return doc
    return {"__root__": doc}


def _load_yaml(path: str) -> object:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def seed(dry_run: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url and not dry_run:
        log.error("DATABASE_URL is required for live run")
        sys.exit(1)

    payload: list[tuple[str, str, object]] = []
    for namespace, rel_path in SOURCE_FILES.items():
        path = Path(rel_path)
        if not path.exists():
            log.warning(f"Skipping missing file: {rel_path}")
            continue
        doc = _load_yaml(rel_path)
        flattened = _flatten_document(doc)
        for key, value in flattened.items():
            payload.append((namespace, str(key), value))

    if dry_run:
        log.info("DRY RUN - no database writes")
        for namespace, key, value in payload:
            rendered = json.dumps(value)[:200]
            log.info(f"upsert app_config ({namespace}, {key}) = {rendered}")
        log.info(f"Total rows prepared: {len(payload)}")
        return

    try:
        import psycopg2
        from psycopg2.extras import Json
    except ImportError:
        log.error("psycopg2 is required. Install with: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            for namespace, key, value in payload:
                cur.execute(
                    """
                    INSERT INTO app_config (namespace, key, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (namespace, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (namespace, key, Json(value)),
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error(f"Seeding failed: {exc}")
        raise
    finally:
        conn.close()

    log.info(f"Seeding complete. Upserted {len(payload)} rows into app_config.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed non-critical config to Postgres app_config")
    parser.add_argument("--dry-run", action="store_true", help="Show planned writes only")
    args = parser.parse_args()

    seed(dry_run=args.dry_run)
