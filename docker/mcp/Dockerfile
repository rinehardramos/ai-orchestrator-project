# Shared base image for generic MCP servers.
#
# One image ships all three packages (worker_mcp, info_broker_mcp,
# obsidian_vault_mcp). The entrypoint is chosen per-container via the
# command (e.g. ``python -m worker_mcp``). Claude Code registers each
# as a separate stdio server via ``docker run --rm -i``.
#
# Build with:
#   docker build -t mcp-servers:latest -f docker/mcp/Dockerfile docker/mcp
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy every package under packages/ onto the Python path.
COPY packages /app/packages
ENV PYTHONPATH=/app/packages

# Default command; overridden per container.
CMD ["python", "-m", "worker_mcp"]
