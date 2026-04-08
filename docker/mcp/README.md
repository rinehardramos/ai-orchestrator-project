# Generic MCP servers

Three project-agnostic MCP servers packaged as one shared docker image:

| Package              | Purpose                                           | Env vars                                                                                      |
|----------------------|---------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `worker_mcp`         | Worker CRUD + task dispatch against `worker-api`  | `CONTROL_URL`, `CONTROL_API_KEY`                                                              |
| `info_broker_mcp`    | REST wrapper for the `info-broker` service        | `INFO_BROKER_URL`, `INFO_BROKER_API_KEY`                                                      |
| `obsidian_vault_mcp` | Markdown → Qdrant ingest + search for any vault   | `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_COLLECTION`, `QDRANT_URL`, `EMBEDDING_URL`, `EMBEDDING_MODEL` |

All three are stdio MCP servers. Claude Code spawns a fresh container
per session via `docker run --rm -i`. Nothing runs as a long-lived
daemon.

## Build

```bash
docker compose -f docker/mcp/docker-compose.mcp.yml build
# → image: mcp-servers:latest
```

## Register at user scope

Run these once from any directory. Replace `<your-key>` with real values.

```bash
# worker-mcp — talks to the worker-api running on the control plane
claude mcp add --scope user worker-mcp -- \
  docker run --rm -i \
    -e CONTROL_URL=http://host.docker.internal:8100 \
    -e CONTROL_API_KEY=<your-key> \
    mcp-servers:latest python -m worker_mcp

# info-broker-mcp — talks to the info-broker docker container
claude mcp add --scope user info-broker-mcp -- \
  docker run --rm -i \
    -e INFO_BROKER_URL=http://host.docker.internal:8000 \
    -e INFO_BROKER_API_KEY=<your-info-broker-key> \
    mcp-servers:latest python -m info_broker_mcp

# obsidian-vault-mcp — bind-mounts your vault at /vault inside the container
claude mcp add --scope user obsidian-vault-mcp -- \
  docker run --rm -i \
    -v ${HOME}/Projects/obsidian-notes/obsidian-notes:/vault:ro \
    -e OBSIDIAN_VAULT_PATH=/vault \
    -e OBSIDIAN_COLLECTION=obsidian_vault_v1 \
    -e QDRANT_URL=http://host.docker.internal:6333 \
    -e EMBEDDING_URL=http://host.docker.internal:1234/v1 \
    -e EMBEDDING_MODEL=text-embedding-nomic-embed-code \
    -e EMBEDDING_DIM=3584 \
    mcp-servers:latest python -m obsidian_vault_mcp
```

> **Note:** the obsidian bind mount is `:ro` because the MCP only
> reads the vault; Qdrant owns the indexed state. Drop `:ro` if you
> later want the same image to write to the vault.

## Required services

| MCP                  | Depends on                                                         |
|----------------------|--------------------------------------------------------------------|
| `worker-mcp`         | `worker-api` container running on the control plane (port 8100)    |
| `info-broker-mcp`    | `~/Projects/info-broker` docker compose up on port 8000            |
| `obsidian-vault-mcp` | Qdrant on port 6333 + an embedding endpoint on 1234                |

## Updating

After editing any package under `docker/mcp/packages/`, rebuild the
image — Claude Code will pick up the new code on the next tool call
because each invocation spawns a fresh container:

```bash
docker compose -f docker/mcp/docker-compose.mcp.yml build
```
