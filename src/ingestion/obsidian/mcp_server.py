"""MCP server exposing Obsidian vault tools over stdio.

Tools:
    - ``search_vault(query, k=8, filter=None)``
    - ``get_note(vault_path)``
    - ``sync_vault(mode="incremental", path=None)``
    - ``analyze_vault()``
    - ``apply_vault_optimization(action)``

The ``apply_vault_optimization`` tool is intentionally separate from
``analyze_vault`` so an agent cannot mutate the index by accident —
it must explicitly name one of the allowed actions.
"""
from __future__ import annotations

import logging
from typing import Any

from src.ingestion.obsidian.analyzer import (
    VALID_ACTIONS,
    analyze_vault as _analyze,
    apply_optimization as _apply,
)
from src.ingestion.obsidian.ingestor import ObsidianVaultIngestor

logger = logging.getLogger(__name__)


class ObsidianMcpHandlers:
    """Pure-python tool handlers. Decoupled from the MCP transport so
    they can be unit-tested without spawning a subprocess."""

    def __init__(self, ingestor: ObsidianVaultIngestor) -> None:
        self.ingestor = ingestor

    def search_vault(
        self, query: str, k: int = 8, filter: dict | None = None
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")
        return self.ingestor.search(query=query, k=k, filter=filter)

    def get_note(self, vault_path: str) -> list[dict[str, Any]]:
        if not isinstance(vault_path, str) or not vault_path:
            raise ValueError("vault_path must be a non-empty string")
        return self.ingestor.get_note(vault_path)

    def sync_vault(
        self, mode: str = "incremental", path: str | None = None
    ) -> dict[str, Any]:
        if mode not in ("incremental", "full"):
            raise ValueError(f"mode must be 'incremental' or 'full', got {mode!r}")
        full = mode == "full"
        if path:
            result = self.ingestor.sync_file(path, full=full)
        else:
            result = self.ingestor.sync_all(full=full)
        return result.as_dict()

    def analyze_vault(self) -> dict[str, Any]:
        return _analyze(self.ingestor).as_dict()

    def apply_vault_optimization(self, action: str) -> dict[str, Any]:
        if action not in VALID_ACTIONS:
            raise ValueError(
                f"action must be one of {VALID_ACTIONS}, got {action!r}"
            )
        return _apply(self.ingestor, action)


def run_stdio_server(ingestor: ObsidianVaultIngestor | None = None) -> None:
    """Run the MCP stdio server. Requires the ``mcp`` Python SDK."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "The 'mcp' package is required to run the MCP server. "
            "Install with: pip install mcp"
        ) from exc

    import asyncio
    import json

    if ingestor is None:
        from src.ingestion.obsidian.cli import _default_vault_path

        ingestor = ObsidianVaultIngestor(vault_path=_default_vault_path())

    handlers = ObsidianMcpHandlers(ingestor)
    server: Any = Server("obsidian-vault")

    tools = [
        Tool(
            name="search_vault",
            description="Semantic search over the Obsidian vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 8},
                    "filter": {"type": "object"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_note",
            description="Return all chunks for a single note by vault-relative path.",
            inputSchema={
                "type": "object",
                "properties": {"vault_path": {"type": "string"}},
                "required": ["vault_path"],
            },
        ),
        Tool(
            name="sync_vault",
            description="Trigger a vault sync. mode=incremental|full, optional path for single-file sync.",
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["incremental", "full"],
                        "default": "incremental",
                    },
                    "path": {"type": "string"},
                },
            },
        ),
        Tool(
            name="analyze_vault",
            description="Return a vault + index analysis report (read-only).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="apply_vault_optimization",
            description="Apply a named optimization: prune, rechunk, or resync.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(VALID_ACTIONS),
                    }
                },
                "required": ["action"],
            },
        ),
    ]

    @server.list_tools()
    async def _list_tools():  # type: ignore[no-untyped-def]
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):  # type: ignore[no-untyped-def]
        try:
            if name == "search_vault":
                result = handlers.search_vault(**arguments)
            elif name == "get_note":
                result = handlers.get_note(**arguments)
            elif name == "sync_vault":
                result = handlers.sync_vault(**arguments)
            elif name == "analyze_vault":
                result = handlers.analyze_vault()
            elif name == "apply_vault_optimization":
                result = handlers.apply_vault_optimization(**arguments)
            else:
                raise ValueError(f"unknown tool {name!r}")
        except Exception as exc:
            return [TextContent(type="text", text=f"error: {exc}")]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    run_stdio_server()
