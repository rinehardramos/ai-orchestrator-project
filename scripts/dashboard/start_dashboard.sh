#!/bin/bash
set -e

source .venv/bin/activate
export DATABASE_URL="postgres://temporal:temporal@localhost:5432/orchestrator"
python -m uvicorn src.tools_catalog.api.http_server:app --factory --host 127.0.0.1 --port 8000

