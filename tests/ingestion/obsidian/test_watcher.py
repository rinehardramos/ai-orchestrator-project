"""Watcher tests — use the public enqueue() entrypoint so we don't depend
on real watchdog FS events in CI."""
from __future__ import annotations

import time

from src.ingestion.obsidian.watcher import VaultWatcher


class RecordingIngestor:
    def __init__(self) -> None:
        self.vault_path = "/fake/vault"
        self.sync_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.sync_all_called = 0

    def sync_file(self, path, full=False):  # noqa: ARG002
        self.sync_calls.append(str(path))

        class _R:
            pass

        return _R()

    def delete_file(self, vault_path):
        self.delete_calls.append(vault_path)

        class _R:
            pass

        return _R()

    def sync_all(self, full=False):  # noqa: ARG002
        self.sync_all_called += 1

        class _R:
            pass

        return _R()


def _drain_watcher(watcher: VaultWatcher, max_wait: float = 1.0):
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        ready = watcher._drain_ready()
        if ready:
            for ev in ready:
                if ev.op == "delete":
                    watcher.ingestor.delete_file(ev.vault_path)
                else:
                    watcher.ingestor.sync_file(ev.vault_path)
        time.sleep(0.02)


def test_debounce_coalesces_rapid_events():
    ing = RecordingIngestor()
    w = VaultWatcher(ing, debounce_ms=100)
    for _ in range(5):
        w.enqueue("sync", "a.md")
        time.sleep(0.01)
    # Before debounce elapses, nothing is ready.
    assert w._drain_ready() == []
    time.sleep(0.15)
    ready = w._drain_ready()
    assert len(ready) == 1
    assert ready[0].vault_path == "a.md"


def test_modify_triggers_sync():
    ing = RecordingIngestor()
    w = VaultWatcher(ing, debounce_ms=50)
    w.enqueue("sync", "note.md")
    _drain_watcher(w)
    assert "note.md" in ing.sync_calls


def test_delete_triggers_delete_file():
    ing = RecordingIngestor()
    w = VaultWatcher(ing, debounce_ms=50)
    w.enqueue("delete", "gone.md")
    _drain_watcher(w)
    assert "gone.md" in ing.delete_calls


def test_rename_is_delete_plus_sync():
    ing = RecordingIngestor()
    w = VaultWatcher(ing, debounce_ms=50)
    w.enqueue("delete", "old.md")
    w.enqueue("sync", "new.md")
    _drain_watcher(w)
    assert "old.md" in ing.delete_calls
    assert "new.md" in ing.sync_calls


def test_startup_reconciliation_runs_once():
    ing = RecordingIngestor()
    w = VaultWatcher(ing, debounce_ms=50)
    # Call reconciliation manually (start() also spawns a real watchdog
    # observer which we avoid in tests).
    ing.sync_all_called = 0
    w.ingestor.sync_all(full=False)
    assert ing.sync_all_called == 1
