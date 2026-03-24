"""
Tool plugin base classes.

Every capability in the system is a Tool — a Python class that exposes
atomic functions to the agent and/or listens for incoming tasks.

Two surfaces per tool (they never cross):
  - start_listener()        → system-only, genesis node, always-on ingestion
  - get_tool_schemas()      → agent-facing, worker node, action functions

Usage:
    class MyTool(Tool):
        type = "email"
        name = "my_tool"
        description = "Does something useful"
        node = "worker"

        def get_tool_schemas(self):
            return [{"type": "function", "function": {"name": "do_thing", ...}}]

        async def call_tool(self, tool_name, args, ctx):
            if tool_name == "do_thing":
                return self._do_thing(**args)

    tool_class = MyTool   # REQUIRED — loader instantiates from this
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
import uuid
import time


@dataclass
class Envelope:
    """
    Universal message container. Travels from source tool → scheduler → worker.

    The source tool constructs this and passes it to on_message().
    The scheduler forwards it to Temporal.
    The worker unpacks it to build the agent's task context.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""                    # tool instance name: "telegram", "sqs_orders"
    timestamp: float = field(default_factory=time.time)

    # Payload — native Python type. Loader/bus handles serialization for transport.
    # str for text tasks, dict for structured data, bytes for audio/video/binary.
    payload: Any = None
    content_type: str = "text/plain"    # MIME hint: "text/plain", "application/json",
                                        # "audio/wav", "video/mp4", "application/octet-stream"

    # Routing
    reply_to: str = ""                  # where to send result, defaults to source
    correlation_id: str = ""            # links a result envelope back to its request

    # Agent interface
    task_description: str = ""          # what the agent should do — plain text
    metadata: dict = field(default_factory=dict)  # source-specific extras

    # Tool scoping — controls which tool instances the agent can see for this task.
    # None = all tools visible (default for CLI, HTTP, generic tasks).
    # ["gmail_work", "shell", "filesystem"] = agent only sees these instances.
    #
    # Source tools set this when submitting tasks to prevent cross-account mistakes.
    # Example: gmail_work listener sets tool_scope=["gmail_work", "shell", "filesystem", "web"]
    # so the agent can't accidentally reply using gmail_personal.
    tool_scope: list = None


@dataclass
class ToolContext:
    """
    Per-task context injected by the worker into every call_tool() invocation.
    Carries state the agent doesn't send — the tool receives it automatically.

    Example:
        async def call_tool(self, tool_name, args, ctx):
            # ctx.workspace_dir is the isolated directory for this task
            path = os.path.join(ctx.workspace_dir, args["filename"])
    """
    workspace_dir: str = ""             # isolated directory for this task's files
    task_id: str = ""                   # Temporal workflow ID
    envelope: Envelope = field(default_factory=Envelope)  # original incoming envelope


class Tool(ABC):
    """
    Base class for all tools. Subclass this to create a new tool plugin.

    Required class attributes:
        type        Category string: "chat", "email", "code", "data", "queue", etc.
        name        Default instance name. Overridden by loader with DB/config key.
        description Human-readable summary shown in tool list header.

    Optional class attributes:
        listen      If True, genesis node calls start_listener() at startup.
        node        Where this tool loads: "genesis", "worker", or "both" (default).

    Required exports at module level:
        tool_class = MyTool   (the class itself, not an instance)
    """

    type: str = ""
    name: str = ""
    description: str = ""
    listen: bool = False
    node: str = "both"

    def initialize(self, config: dict) -> None:
        """
        Called once at startup with config from DB or tools.yaml.
        Store credentials and settings here. Do NOT make network calls here —
        defer connections to the first actual call_tool() invocation.
        """
        self.config = config

    @abstractmethod
    def get_tool_schemas(self) -> list[dict]:
        """
        Return OpenAI-compatible function schemas for agent-facing tools.
        Listener-only tools (e.g. http_server) return [].

        Use GENERIC function names — no instance prefix.
        The registry adds the instance prefix automatically.

        Example:
            return [{"type": "function", "function": {
                "name": "email_send",           # generic, NOT "gmail_work__email_send"
                "description": "Send an email. Use when task requires sending email.",
                "parameters": {"type": "object", "properties": {
                    "to":      {"type": "string"},
                    "subject": {"type": "string"},
                    "body":    {"type": "string"}
                }, "required": ["to", "subject", "body"]}
            }}]
        """
        ...

    @abstractmethod
    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        """
        Execute a tool function by name.

        tool_name: matches a name from get_tool_schemas() (WITHOUT instance prefix)
        args:      dict of arguments from the agent (matches the schema parameters)
        ctx:       ToolContext with workspace_dir, task_id, envelope

        Return a string result the agent can read, or raise an exception on failure.
        """
        ...

    async def deliver_result(self, envelope: Envelope, result: str,
                             artifacts: list) -> None:
        """
        Called by the scheduler after a task completes to send the result back
        to the source. Override in tools that need custom delivery.

        Default: no-op (tools like chat/sms/db override this).

        envelope:  original envelope that triggered the task
        result:    final text output from the agent
        artifacts: list of dicts with {"filename": str, "path": str, "mime_type": str}
        """
        pass

    # -------------------------------------------------------------------------
    # Listener lifecycle — genesis node only, never called by workers/agents
    # -------------------------------------------------------------------------

    async def start_listener(self, on_message: Callable[[Envelope], Any]) -> None:
        """
        Called by genesis at startup for tools with listen=True.
        Start polling, bind a port, subscribe to events, etc.
        Call on_message(envelope) whenever a new task arrives.

        on_message is scheduler.submit_task — it enqueues the task to Temporal.
        """
        pass

    async def stop_listener(self) -> None:
        """Called by genesis at shutdown. Clean up connections, stop polling."""
        pass
