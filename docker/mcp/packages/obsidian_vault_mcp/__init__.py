"""Generic Obsidian-vault MCP server.

Env-driven. Works against any vault on a bind-mounted path + any
OpenAI-compatible embedding endpoint + any Qdrant.

Env vars:
  * ``OBSIDIAN_VAULT_PATH``   — path inside the container (default ``/vault``)
  * ``OBSIDIAN_COLLECTION``   — Qdrant collection (default ``obsidian_vault_v1``)
  * ``QDRANT_URL``            — Qdrant base URL (default ``http://host.docker.internal:6333``)
  * ``EMBEDDING_URL``         — OpenAI-compatible endpoint (default ``http://host.docker.internal:1234/v1``)
  * ``EMBEDDING_MODEL``       — model name (default ``text-embedding-nomic-embed-code``)
  * ``EMBEDDING_DIM``         — dimension (default 3584)
"""
