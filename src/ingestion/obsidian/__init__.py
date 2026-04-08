"""Obsidian vault ingestion package.

Core entry point: :class:`ObsidianVaultIngestor`.
CLI entry point: ``python -m src.ingestion.obsidian``.

The stdio MCP server and real-time watcher daemon have been moved
out of this project tree into ``~/.claude/mcp-servers/packages/
obsidian_vault_mcp`` so any project can use them via the shared
``mcp-servers:latest`` docker image. See
``~/.claude/mcp-servers/README.md``.
"""

from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor, SyncResult
from src.ingestion.obsidian.parser import Chunk, ParsedNote, parse_note

__all__ = [
    "ObsidianVaultIngestor",
    "SyncResult",
    "Chunk",
    "ParsedNote",
    "parse_note",
]
