"""Real-time vault watcher.

Uses ``watchdog`` to observe filesystem events under the vault root and
dispatches coalesced, debounced sync calls to an
:class:`ObsidianVaultIngestor`. Intended to be the primary long-running
mode: saving a note in Obsidian makes it searchable within ~1 second.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.ingestion.obsidian.ingestor import (
    DEFAULT_IGNORE_GLOBS,
    ObsidianVaultIngestor,
)

logger = logging.getLogger(__name__)


@dataclass
class _PendingEvent:
    op: str  # "sync" or "delete"
    due_at: float
    vault_path: str


class VaultWatcher:
    """Watch a vault directory and trigger debounced incremental syncs."""

    def __init__(
        self,
        ingestor: ObsidianVaultIngestor,
        debounce_ms: int = 500,
        ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
        poll_interval: float = 0.05,
    ) -> None:
        self.ingestor = ingestor
        self.debounce = debounce_ms / 1000.0
        self.ignore_globs = tuple(ignore_globs)
        self.poll_interval = poll_interval

        self._pending: dict[str, _PendingEvent] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._observer = None

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------
    def _should_ignore(self, vault_path: str) -> bool:
        return any(fnmatch.fnmatch(vault_path, pat) for pat in self.ignore_globs)

    def _to_vault_path(self, abs_path: str) -> Optional[str]:
        try:
            rel = os.path.relpath(abs_path, self.ingestor.vault_path)
        except ValueError:
            return None
        if rel.startswith(".."):
            return None
        if not rel.endswith(".md"):
            return None
        if self._should_ignore(rel):
            return None
        return rel

    def enqueue(self, op: str, vault_path: str) -> None:
        """Public entry point used by the watchdog handler and tests."""
        with self._lock:
            self._pending[vault_path] = _PendingEvent(
                op=op, due_at=time.monotonic() + self.debounce, vault_path=vault_path
            )

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------
    def _drain_ready(self) -> list[_PendingEvent]:
        now = time.monotonic()
        ready: list[_PendingEvent] = []
        with self._lock:
            for key in list(self._pending.keys()):
                ev = self._pending[key]
                if ev.due_at <= now:
                    ready.append(ev)
                    del self._pending[key]
        return ready

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            for ev in self._drain_ready():
                try:
                    if ev.op == "delete":
                        self.ingestor.delete_file(ev.vault_path)
                    else:
                        self.ingestor.sync_file(ev.vault_path)
                except Exception as exc:  # pragma: no cover - degraded path
                    logger.exception("Watcher sync failed for %s: %s", ev.vault_path, exc)
            self._stop.wait(self.poll_interval)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, startup_reconciliation: bool = True) -> None:
        if startup_reconciliation:
            logger.info("Watcher startup reconciliation starting")
            self.ingestor.sync_all(full=False)

        self._stop.clear()
        self._worker = threading.Thread(
            target=self._worker_loop, name="obsidian-watcher", daemon=True
        )
        self._worker.start()

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "watchdog is required for VaultWatcher.start(); install it"
            ) from exc

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):  # type: ignore[override]
                if event.is_directory:
                    return
                vp = watcher._to_vault_path(event.src_path)
                if vp:
                    watcher.enqueue("sync", vp)

            def on_modified(self, event):  # type: ignore[override]
                if event.is_directory:
                    return
                vp = watcher._to_vault_path(event.src_path)
                if vp:
                    watcher.enqueue("sync", vp)

            def on_deleted(self, event):  # type: ignore[override]
                if event.is_directory:
                    return
                vp = watcher._to_vault_path(event.src_path)
                if vp:
                    watcher.enqueue("delete", vp)

            def on_moved(self, event):  # type: ignore[override]
                if event.is_directory:
                    return
                old_vp = watcher._to_vault_path(event.src_path)
                new_vp = watcher._to_vault_path(event.dest_path)
                if old_vp:
                    watcher.enqueue("delete", old_vp)
                if new_vp:
                    watcher.enqueue("sync", new_vp)

        self._observer = Observer()
        self._observer.schedule(
            _Handler(), str(self.ingestor.vault_path), recursive=True
        )
        self._observer.start()
        logger.info("Watcher started on %s", self.ingestor.vault_path)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=timeout)
            except Exception:  # pragma: no cover
                pass
            self._observer = None
        if self._worker is not None:
            self._worker.join(timeout=timeout)
            self._worker = None

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------
    def flush_pending(self, max_wait: float = 2.0) -> None:
        """Block until the pending queue is empty. Used by tests."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            with self._lock:
                if not self._pending:
                    return
            time.sleep(self.poll_interval)
