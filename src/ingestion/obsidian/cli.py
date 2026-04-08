"""Command-line entry point for the Obsidian ingestion tool.

Usage::

    python -m src.ingestion.obsidian sync [--full] [--path FILE] [--vault DIR]
    python -m src.ingestion.obsidian watch [--vault DIR]
    python -m src.ingestion.obsidian analyze [--apply {prune,rechunk,resync}]
    python -m src.ingestion.obsidian search QUERY [-k N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path

from src.ingestion.obsidian.analyzer import analyze_vault, apply_optimization
from src.ingestion.obsidian.ingestor import DEFAULT_COLLECTION, ObsidianVaultIngestor
from src.ingestion.obsidian.watcher import VaultWatcher

logger = logging.getLogger("obsidian.cli")


def _default_vault_path() -> str:
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return env
    try:
        import yaml  # type: ignore

        settings_path = Path(__file__).resolve().parents[3] / "config" / "settings.yaml"
        if settings_path.exists():
            with settings_path.open("r") as f:
                data = yaml.safe_load(f) or {}
            vp = (data.get("obsidian") or {}).get("vault_path")
            if vp:
                return os.path.expanduser(vp)
    except Exception:
        pass
    return os.path.expanduser("~/Projects/obsidian-vault")


def _make_ingestor(args: argparse.Namespace) -> ObsidianVaultIngestor:
    vault = args.vault or _default_vault_path()
    return ObsidianVaultIngestor(vault_path=vault, collection=args.collection)


def _cmd_sync(args: argparse.Namespace) -> int:
    ing = _make_ingestor(args)
    if args.path:
        result = ing.sync_file(args.path, full=args.full)
    else:
        result = ing.sync_all(full=args.full)
    print(json.dumps(result.as_dict(), indent=2))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    ing = _make_ingestor(args)
    watcher = VaultWatcher(ing, debounce_ms=args.debounce_ms)
    watcher.start(startup_reconciliation=not args.no_reconcile)
    print(
        f"Watching {ing.vault_path} → collection={ing.collection}. Press Ctrl-C to stop.",
        flush=True,
    )
    stop = {"flag": False}

    def _handle(signum, frame):  # noqa: ARG001
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        while not stop["flag"]:
            signal.pause() if hasattr(signal, "pause") else None
    finally:
        watcher.stop()
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    ing = _make_ingestor(args)
    if args.apply:
        result = apply_optimization(ing, args.apply)
        print(json.dumps(result, indent=2, default=str))
        return 0
    report = analyze_vault(ing)
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    ing = _make_ingestor(args)
    hits = ing.search(args.query, k=args.k)
    print(json.dumps(hits, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="obsidian")
    p.add_argument("--vault", help="Path to the Obsidian vault")
    p.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="Qdrant collection name (default: %(default)s)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync", help="One-shot sync")
    ps.add_argument("--full", action="store_true", help="Re-embed every chunk")
    ps.add_argument("--path", help="Sync a single file (relative to vault)")
    ps.set_defaults(func=_cmd_sync)

    pw = sub.add_parser("watch", help="Real-time sync daemon")
    pw.add_argument("--debounce-ms", type=int, default=500)
    pw.add_argument("--no-reconcile", action="store_true")
    pw.set_defaults(func=_cmd_watch)
    sub.add_parser("daemon", parents=[pw], add_help=False)  # alias

    pa = sub.add_parser("analyze", help="Analyze the vault and index")
    pa.add_argument("--apply", choices=["prune", "rechunk", "resync"])
    pa.set_defaults(func=_cmd_analyze)

    psr = sub.add_parser("search", help="Semantic search")
    psr.add_argument("query")
    psr.add_argument("-k", type=int, default=8)
    psr.set_defaults(func=_cmd_search)

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("OBSIDIAN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
