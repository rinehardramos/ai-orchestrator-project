"""
Tool Registry.

Holds all loaded tool instances. Provides O(1) routing of agent tool calls
to the correct tool instance via a pre-built lookup dict.

Usage:
    from src.plugins.registry import registry

    # Get all tool schemas for the agent (call once per task)
    schemas = registry.get_all_tool_schemas(specialization="coding")

    # Execute a tool call from the agent (in the ReAct loop)
    result = await registry.call_tool("gmail_work__email_send", args, ctx)

    # Get a specific tool instance by name (for result delivery)
    tool = registry.get("telegram")
    await tool.deliver_result(envelope, result, artifacts)
"""

from __future__ import annotations
import logging
import os
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.plugins.base import Tool, ToolContext

log = logging.getLogger(__name__)


class ToolNotFound(Exception):
    """Raised when the agent calls a function name that no tool handles."""
    pass


class ToolRegistry:
    def __init__(self):
        # instance_name → Tool instance
        self._tools: dict[str, "Tool"] = {}
        # namespaced_fn_name → instance_name  (O(1) lookup for call_tool)
        # e.g. "gmail_work__email_send" → "gmail_work"
        self._fn_lookup: dict[str, str] = {}
        # Cached specialization filter data from profiles.yaml
        self._specializations: Optional[dict] = None

    def register(self, tool: "Tool") -> None:
        """Register a tool instance. Builds the O(1) function lookup dict."""
        self._tools[tool.name] = tool
        for schema in tool.get_tool_schemas():
            fn_name = schema["function"]["name"]
            namespaced = f"{tool.name}__{fn_name}"
            self._fn_lookup[namespaced] = tool.name
        log.debug(f"Registered tool: {tool.name} with "
                  f"{len(tool.get_tool_schemas())} functions")

    def get(self, name: str) -> "Optional[Tool]":
        """Get a tool instance by its instance name."""
        return self._tools.get(name)

    def get_all_tool_schemas(self, specialization: str = None,
                             tool_scope: list = None) -> list[dict]:
        """
        Return namespaced OpenAI-compatible schemas for the agent.

        Each function name is prefixed with the tool instance name so the agent
        can distinguish multiple instances of the same tool type
        (e.g. gmail_work__email_send vs gmail_personal__email_send).

        specialization: if provided, filters to allowed function names from
                        profiles.yaml (e.g. "coding" only gets shell, filesystem).
        tool_scope:     if provided, only include these tool instance names.
                        Set by the Envelope when a source tool wants to restrict
                        which tools the agent can see for this specific task.
                        Example: ["gmail_work", "shell", "filesystem", "web"]
                        None = all tools visible (default).
        """
        schemas = []
        for tool in self._tools.values():
            # Skip tools not in scope (if scope is set)
            if tool_scope is not None and tool.name not in tool_scope:
                continue

            for schema in tool.get_tool_schemas():
                fn_name = schema["function"]["name"]
                namespaced = {
                    "type": schema.get("type", "function"),
                    "function": {
                        **schema["function"],
                        "name": f"{tool.name}__{fn_name}",
                        "description": f"[{tool.name}] {schema['function'].get('description', '')}",
                    }
                }
                schemas.append(namespaced)

        if specialization:
            schemas = self._filter_by_specialization(schemas, specialization)

        return schemas

    async def call_tool(self, namespaced_name: str, args: dict,
                        ctx: "ToolContext") -> Any:
        """
        Route a tool call from the agent to the correct tool instance.
        Uses O(1) lookup — does NOT iterate all tools or schemas.

        namespaced_name: "gmail_work__email_send" (as the agent received it)
        args:            dict of arguments from the agent
        ctx:             ToolContext with workspace_dir, task_id, envelope
        """
        if namespaced_name not in self._fn_lookup:
            raise ToolNotFound(
                f"No tool registered for function: {namespaced_name}. "
                f"Available: {sorted(self._fn_lookup.keys())[:10]}..."
            )
        instance_name = self._fn_lookup[namespaced_name]
        fn_name = namespaced_name.split("__", 1)[1]
        tool = self._tools[instance_name]
        return await tool.call_tool(fn_name, args, ctx)

    def get_listeners(self) -> list["Tool"]:
        """Return all tools that have listen=True (always-on ingestion sources)."""
        return [t for t in self._tools.values() if t.listen]

    def list_tools(self) -> list[dict]:
        """Return summary of all registered tools for display/API."""
        return [
            {
                "name": t.name,
                "type": t.type,
                "description": t.description,
                "listen": t.listen,
                "node": t.node,
                "functions": [s["function"]["name"] for s in t.get_tool_schemas()],
            }
            for t in self._tools.values()
        ]

    def reload(self) -> None:
        """Clear all registered tools. Caller must re-run load_tools() after."""
        self._tools.clear()
        self._fn_lookup.clear()
        self._specializations = None
        log.info("Registry cleared — reload required")

    def refresh_specializations(self) -> bool:
        """
        Reload specializations from database.
        Returns True if specializations were reloaded.
        """
        try:
            self._specializations = self._load_specializations()
            log.info(f"Refreshed specializations: {list(self._specializations.keys())}")
            return True
        except Exception as e:
            log.error(f"Failed to refresh specializations: {e}")
            return False

    def check_and_reload_config(self) -> bool:
        """
        Check if config has changed and reload if needed.
        Returns True if reload happened.
        """
        try:
            from src.config_db import get_loader
            loader = get_loader()
            if loader.has_config_changed():
                log.info("Config change detected, reloading...")
                loader.invalidate_cache()
                self.refresh_specializations()
                return True
        except Exception as e:
            log.warning(f"Config change check failed: {e}")
        return False

    def _filter_by_specialization(self, schemas: list[dict],
                                   specialization: str) -> list[dict]:
        """
        Filter schemas to only include tools allowed for this specialization.
        Reads allowed_tools from config/profiles.yaml.

        The allowed_tools list uses the generic function name (e.g. "read_file"),
        not the namespaced name (e.g. "filesystem__read_file").
        We match on the part after __ in the namespaced name.
        """
        allowed = self._get_allowed_tools(specialization)
        if not allowed:
            return schemas  # no filter for unknown specialization

        filtered = []
        for schema in schemas:
            fn_full = schema["function"]["name"]  # "filesystem__read_file"
            # Extract generic name after __
            if "__" in fn_full:
                fn_generic = fn_full.split("__", 1)[1]
            else:
                fn_generic = fn_full
            if fn_generic in allowed:
                filtered.append(schema)
        return filtered

    def _get_allowed_tools(self, specialization: str) -> list[str]:
        """Load allowed_tools list for a specialization from DB."""
        if self._specializations is None:
            self._specializations = self._load_specializations()
        spec = self._specializations.get(specialization, {})
        # Note: 'allowed_tools' key in DB is stored as a list
        return spec.get("allowed_tools", [])

    def _load_specializations(self) -> dict:
        """Read specializations from database (app_config table)."""
        try:
            from src.config_db import get_loader
            loader = get_loader()
            return loader.get_specializations()
        except Exception as e:
            log.error(f"Could not load specializations from DB: {e}")
            # Fallback to minimal default to allow system to start
            return {
                "general": {"allowed_tools": ["shell", "filesystem", "web"]}
            }


# Global singleton — one per process.
# Genesis has its own registry (listener tools).
# Each worker has its own registry (action tools).
registry = ToolRegistry()
