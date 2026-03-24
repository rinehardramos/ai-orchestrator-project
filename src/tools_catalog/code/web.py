"""
Web tool — search the web and fetch URL content.

Wraps search_web and read_url_content from src/execution/worker/tools.py.
"""
from __future__ import annotations

from src.plugins.base import Tool, ToolContext
from src.execution.worker.tools import (
    search_web as _search_web,
    read_url_content as _read_url_content,
)


class WebTool(Tool):
    type = "code"
    name = "web"
    description = "Search the web and fetch content from URLs"
    node = "worker"

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": (
                        "Search the web using DuckDuckGo. "
                        "Returns titles, URLs, and snippets for the top results. "
                        "Use when you need current information or facts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "description": (
                        "Fetch and extract readable text from a URL. "
                        "Strips HTML, scripts, and styles. "
                        "Use to read articles, docs, or web pages."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Full URL to fetch (must start with http:// or https://)",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        if tool_name == "search_web":
            return _search_web(ctx.workspace_dir, **args)
        if tool_name == "fetch_url":
            return _read_url_content(ctx.workspace_dir, **args)
        return f"ERROR: Unknown tool '{tool_name}'"


tool_class = WebTool
