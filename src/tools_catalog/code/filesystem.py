"""
Filesystem tool — read, write, edit, and navigate files in the workspace.

Wraps read_file, write_file, edit_file, list_files, search_files
from src/execution/worker/tools.py.
"""
from __future__ import annotations

from src.plugins.base import Tool, ToolContext
from src.execution.worker.tools import (
    read_file as _read_file,
    write_file as _write_file,
    edit_file as _edit_file,
    list_files as _list_files,
    search_files as _search_files,
)


class FilesystemTool(Tool):
    type = "code"
    name = "filesystem"
    description = "Read, write, edit, list, and search files in the task workspace"
    node = "worker"

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "Read a file with line numbers. "
                        "Use offset and limit for large files."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to workspace",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Line number to start reading from (0-based)",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of lines to return",
                                "default": 2000,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Create or overwrite a file with new content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to workspace",
                            },
                            "content": {
                                "type": "string",
                                "description": "Full content to write to the file",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": (
                        "Replace the first occurrence of old_string with new_string in a file. "
                        "old_string must be unique in the file."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to workspace",
                            },
                            "old_string": {
                                "type": "string",
                                "description": "Exact text to find (must be unique in file)",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Text to replace old_string with",
                            },
                        },
                        "required": ["path", "old_string", "new_string"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List directory tree up to 3 levels deep.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Directory path relative to workspace",
                                "default": ".",
                            },
                            "max_depth": {
                                "type": "integer",
                                "description": "Maximum directory depth to traverse",
                                "default": 3,
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": (
                        "Search for a regex pattern across files using grep. "
                        "Returns matching lines with file names and line numbers."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Regex pattern to search for",
                            },
                            "path": {
                                "type": "string",
                                "description": "Directory to search in (relative to workspace)",
                                "default": ".",
                            },
                            "glob": {
                                "type": "string",
                                "description": "File pattern filter e.g. '*.py', '*.ts'",
                                "default": "",
                            },
                        },
                        "required": ["pattern"],
                    },
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        wd = ctx.workspace_dir
        if tool_name == "read_file":
            return _read_file(wd, **args)
        if tool_name == "write_file":
            return _write_file(wd, **args)
        if tool_name == "edit_file":
            return _edit_file(wd, **args)
        if tool_name == "list_files":
            return _list_files(wd, **args)
        if tool_name == "search_files":
            return _search_files(wd, **args)
        return f"ERROR: Unknown tool '{tool_name}'"


tool_class = FilesystemTool
