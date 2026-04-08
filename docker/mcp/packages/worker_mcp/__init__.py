"""Generic worker MCP server.

HTTP client for any ``worker-api`` instance. Env-driven and project-
agnostic: works against any control plane that exposes the worker-api
HTTP contract.

Env vars:
  * ``CONTROL_URL`` — base URL (default ``http://host.docker.internal:8100``)
  * ``CONTROL_API_KEY`` — static API key for ``X-Control-API-Key`` header
"""
