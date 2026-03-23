import os
import subprocess
import datetime
import logging
import requests
import time

from src.config import load_settings

logger = logging.getLogger("BackupManager")


class BackupManager:
    def __init__(self):
        self.config = load_settings()
        self.backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "backups"
        )
        os.makedirs(self.backup_dir, exist_ok=True)

    def backup_qdrant(self) -> bool:
        """Backup all Qdrant collections using the Snapshot API."""
        qdrant_cfg = self.config.get("qdrant", {})
        host = qdrant_cfg.get("host", "localhost")
        port = qdrant_cfg.get("port", 6333)
        base_url = f"http://{host}:{port}"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            # List all collections
            resp = requests.get(f"{base_url}/collections", timeout=10)
            resp.raise_for_status()
            collections = [c["name"] for c in resp.json().get("result", {}).get("collections", [])]

            if not collections:
                logger.info("No Qdrant collections found to back up.")
                return True

            for collection in collections:
                logger.info(f"Creating snapshot for collection: {collection}")
                snap_resp = requests.post(
                    f"{base_url}/collections/{collection}/snapshots",
                    timeout=60
                )
                snap_resp.raise_for_status()
                snapshot_name = snap_resp.json()["result"]["name"]

                # Poll until snapshot is ready
                for _ in range(30):
                    list_resp = requests.get(
                        f"{base_url}/collections/{collection}/snapshots",
                        timeout=10
                    )
                    list_resp.raise_for_status()
                    snapshots = list_resp.json().get("result", [])
                    ready = any(s["name"] == snapshot_name for s in snapshots)
                    if ready:
                        break
                    time.sleep(2)

                # Download snapshot
                dl_resp = requests.get(
                    f"{base_url}/collections/{collection}/snapshots/{snapshot_name}",
                    stream=True,
                    timeout=120
                )
                dl_resp.raise_for_status()
                backup_file = os.path.join(
                    self.backup_dir,
                    f"qdrant_{collection}_{timestamp}.snapshot"
                )
                with open(backup_file, "wb") as f:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Qdrant snapshot saved: {backup_file}")

            return True

        except requests.exceptions.ConnectionError:
            logger.warning(f"Qdrant not reachable at {base_url} — skipping backup.")
            return False
        except Exception as e:
            logger.error(f"Qdrant backup failed: {e}", exc_info=True)
            return False

    def backup_temporal(self) -> bool:
        """Backup the Temporal Postgres database using pg_dump."""
        pg_cfg = self.config.get("postgres", {})
        qdrant_cfg = self.config.get("qdrant", {})
        # Temporal postgres typically lives on the same host as the control plane
        control_host = qdrant_cfg.get("host", "localhost")

        pg_host = pg_cfg.get("host", control_host)
        pg_port = str(pg_cfg.get("port", 5432))
        pg_user = pg_cfg.get("user", "temporal")
        pg_db = pg_cfg.get("db", "temporal")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(self.backup_dir, f"temporal_db_{timestamp}.sql")

        env = os.environ.copy()
        pg_password = pg_cfg.get("password") or os.environ.get("POSTGRES_PASSWORD")
        if pg_password:
            env["PGPASSWORD"] = pg_password

        try:
            result = subprocess.run(
                ["pg_dump", "-h", pg_host, "-p", pg_port, "-U", pg_user, "-d", pg_db, "-f", backup_file],
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                logger.info(f"Temporal DB backup saved: {backup_file}")
                return True
            else:
                logger.error(f"pg_dump exited {result.returncode}: {result.stderr}")
                return False
        except FileNotFoundError:
            logger.warning("pg_dump not found — install postgresql-client to enable Temporal backups.")
            return False
        except subprocess.TimeoutExpired:
            logger.error("pg_dump timed out after 300s.")
            return False
        except Exception as e:
            logger.error(f"Temporal backup failed: {e}", exc_info=True)
            return False

    def run_all_backups(self) -> dict:
        logger.info("=== Starting System Backups ===")
        results = {
            "qdrant": self.backup_qdrant(),
            "temporal": self.backup_temporal(),
        }
        logger.info(f"=== Backups Completed: {results} ===")
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = BackupManager()
    manager.run_all_backups()
