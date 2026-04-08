"""Obsidian vault ingestion package.

Core entry point: :class:`ObsidianVaultIngestor`.
CLI entry point: ``python -m src.ingestion.obsidian``.
MCP server: :mod:`src.ingestion.obsidian.mcp_server`.
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
