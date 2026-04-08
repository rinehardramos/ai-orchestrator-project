"""Generic info-broker MCP server.

Env-driven HTTP client for any info-broker instance.

Env vars:
  * ``INFO_BROKER_URL`` — base URL (default ``http://host.docker.internal:8000``)
  * ``INFO_BROKER_API_KEY`` — value for the ``X-API-Key`` header
"""
