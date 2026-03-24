"""
Shell tool — execute shell commands inside the task workspace.

Wraps shell_exec from src/execution/worker/tools.py.
The existing implementation is reused directly — no logic changes.
"""
from __future__ import annotations

from src.plugins.base import Tool, ToolContext
from src.execution.worker.tools import shell_exec as _shell_exec


class ShellTool(Tool):
    type = "code"
    name = "shell"
    description = "Execute shell commands inside the task workspace"
    node = "worker"

    def initialize(self, config: dict) -> None:
        self.config = config
        # Allow tools.yaml to override the timeout
        timeout = config.get("timeout_seconds")
        if timeout:
            import src.execution.worker.tools as _tools
            _tools.SHELL_TIMEOUT = int(timeout)

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "shell_exec",
                    "description": (
                        "Run a shell command in the task workspace. "
                        "Use for compiling, running scripts, installing packages, "
                        "checking output of programs. Sandboxed. 120s timeout."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The shell command to run",
                            },
                        },
                        "required": ["command"],
                    },
                },
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        if tool_name == "shell_exec":
            return _shell_exec(ctx.workspace_dir, **args)
        return f"ERROR: Unknown tool '{tool_name}'"


tool_class = ShellTool
