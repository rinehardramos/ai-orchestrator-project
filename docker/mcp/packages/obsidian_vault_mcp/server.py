"""stdio MCP server for the generic Obsidian vault tool."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from obsidian_vault_mcp.ingestor import ObsidianVaultIngestor

log = logging.getLogger(__name__)


def run() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    ingestor = ObsidianVaultIngestor()
    server: Any = Server("obsidian-vault-mcp")

    tools = [
        Tool(
            name="search_vault",
            description="Semantic search over the Obsidian vault collection.",
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
            description="Return all chunks for a vault-relative note path in heading order.",
            inputSchema={
                "type": "object",
                "properties": {"vault_path": {"type": "string"}},
                "required": ["vault_path"],
            },
        ),
        Tool(
            name="sync_vault",
            description=(
                "Trigger a sync. mode='incremental' (default) uses hash-diff; "
                "'full' re-embeds everything. Optional 'path' scopes to one file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["incremental", "full"], "default": "incremental"},
                    "path": {"type": "string"},
                },
            },
        ),
        Tool(
            name="prune_orphans",
            description="Delete Qdrant points whose source file is no longer present on disk.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

    def _search(query: str, k: int = 8, filter: Optional[dict] = None) -> Any:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty")
        return ingestor.search(query=query, k=k, filter=filter)

    def _get_note(vault_path: str) -> Any:
        if not isinstance(vault_path, str) or not vault_path:
            raise ValueError("vault_path must be non-empty")
        return ingestor.get_note(vault_path)

    def _sync(mode: str = "incremental", path: Optional[str] = None) -> Any:
        if mode not in ("incremental", "full"):
            raise ValueError("mode must be 'incremental' or 'full'")
        full = mode == "full"
        if path:
            return ingestor.sync_file(path, full=full).as_dict()
        return ingestor.sync_all(full=full).as_dict()

    def _prune() -> Any:
        return {"removed": ingestor.prune_orphans()}

    dispatch = {
        "search_vault": _search,
        "get_note": _get_note,
        "sync_vault": _sync,
        "prune_orphans": _prune,
    }

    @server.list_tools()
    async def _list():  # type: ignore[no-untyped-def]
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict):  # type: ignore[no-untyped-def]
        arguments = arguments or {}
        fn = dispatch.get(name)
        if fn is None:
            return [TextContent(type="text", text=f"error: unknown tool {name!r}")]
        try:
            result = fn(**arguments)
        except Exception as exc:
            return [TextContent(type="text", text=f"error: {exc}")]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())
