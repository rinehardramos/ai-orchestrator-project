"""
Git tool — clone, commit, branch, and push git repositories.

Wraps git_clone, git_commit, git_create_branch, git_push
from src/execution/worker/tools.py.
"""
from __future__ import annotations

from src.plugins.base import Tool, ToolContext
from src.execution.worker.tools import (
    git_clone as _git_clone,
    git_commit as _git_commit,
    git_create_branch as _git_create_branch,
    git_push as _git_push,
)


class GitTool(Tool):
    type = "code"
    name = "git"
    description = "Git operations: clone, commit, branch, push"
    node = "worker"

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "git_clone",
                    "description": (
                        "Clone a git repository into the workspace. "
                        "Uses GITHUB_TOKEN from environment for authentication."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_url": {
                                "type": "string",
                                "description": "Repository URL (HTTPS or SSH)",
                            },
                            "target_dir": {
                                "type": "string",
                                "description": "Directory name to clone into",
                                "default": "repo",
                            },
                            "shallow": {
                                "type": "boolean",
                                "description": "Use --depth=1 for faster clone (omits full history)",
                                "default": True,
                            },
                        },
                        "required": ["repo_url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_commit",
                    "description": "Stage all changes and create a commit.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Commit message",
                            },
                            "path": {
                                "type": "string",
                                "description": "Path to the repo directory (relative to workspace)",
                                "default": ".",
                            },
                        },
                        "required": ["message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_create_branch",
                    "description": "Create and switch to a new git branch.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "branch_name": {
                                "type": "string",
                                "description": "Name of the new branch",
                            },
                            "path": {
                                "type": "string",
                                "description": "Path to the repo directory",
                                "default": ".",
                            },
                        },
                        "required": ["branch_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_push",
                    "description": (
                        "Push commits to the remote repository. "
                        "Requires GITHUB_TOKEN environment variable."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the repo directory",
                                "default": ".",
                            },
                            "remote": {
                                "type": "string",
                                "description": "Remote name",
                                "default": "origin",
                            },
                            "branch": {
                                "type": "string",
                                "description": "Branch name (defaults to current branch)",
                                "default": "",
                            },
                        },
                        "required": [],
                    },
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        wd = ctx.workspace_dir
        if tool_name == "git_clone":
            return _git_clone(wd, **args)
        if tool_name == "git_commit":
            return _git_commit(wd, **args)
        if tool_name == "git_create_branch":
            return _git_create_branch(wd, **args)
        if tool_name == "git_push":
            return _git_push(wd, **args)
        return f"ERROR: Unknown tool '{tool_name}'"


tool_class = GitTool
