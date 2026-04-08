"""Obsidian vault ingestion package.

Core entry point: :class:`ObsidianVaultIngestor`.
CLI entry point: ``python -m src.ingestion.obsidian``.

The stdio MCP server has been moved to the generic, containerized
``docker/mcp/packages/obsidian_vault_mcp`` package so any project can
use it. See ``docker/mcp/README.md``.
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
