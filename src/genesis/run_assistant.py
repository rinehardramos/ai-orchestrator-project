"""Dispatch the ``assistant`` specialized worker.

Reads the ``AGENT INSTRUCTIONS`` note from the Obsidian vault collection
in Qdrant (synced by ``src.ingestion.obsidian``), then submits its
contents as an agent task with ``specialization="assistant"``. The
existing worker on the ai-orchestration-queue picks it up, looks up the
specialization in the ``specializations`` config namespace, and runs the
ReAct loop with the local Gemma model in LM Studio.

Usage::

    python -m src.genesis.run_assistant
    python -m src.genesis.run_assistant --note "OTHER NOTE.md"
    python -m src.genesis.run_assistant --dry-run     # print payload, do not submit

This is a thin Genesis-side delegator. All execution still happens on
the worker plane via Temporal.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.control.orchestrator.scheduler import TaskScheduler
from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor

DEFAULT_NOTE = "AGENT INSTRUCTIONS.md"
DEFAULT_SPECIALIZATION = "assistant"

logger = logging.getLogger("genesis.run_assistant")


def load_instructions(note_name: str, vault_path: str | None = None) -> str:
    """Fetch every chunk of ``note_name`` from Qdrant and concatenate them."""
    ingestor = ObsidianVaultIngestor(
        vault_path=vault_path or "~/Projects/obsidian-notes/obsidian-notes"
    )
    chunks = ingestor.get_note(note_name)
    if not chunks:
        raise LookupError(
            f"Note {note_name!r} not found in Qdrant. "
            f"Sync it first with: python -m src.ingestion.obsidian sync"
        )
    return "\n\n".join(c.get("content", "") for c in chunks).strip()


async def dispatch(note_name: str, vault_path: str | None, dry_run: bool) -> int:
    instructions = load_instructions(note_name, vault_path=vault_path)
    if not instructions:
        logger.error("Note %r is empty after concatenation", note_name)
        return 2

    analysis = {"specialization": DEFAULT_SPECIALIZATION}

    if dry_run:
        print("─── assistant payload (dry-run) ───")
        print(f"specialization: {DEFAULT_SPECIALIZATION}")
        print(f"note: {note_name}")
        print(f"instructions ({len(instructions)} chars):")
        print(instructions)
        return 0

    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    task_id = await scheduler.submit_agent_task(
        task_description=instructions,
        analysis_result=analysis,
    )
    print(task_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_assistant")
    parser.add_argument("--note", default=DEFAULT_NOTE, help="Vault-relative note path")
    parser.add_argument("--vault", default=None, help="Override vault path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        return asyncio.run(dispatch(args.note, args.vault, args.dry_run))
    except LookupError as exc:
        logger.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
