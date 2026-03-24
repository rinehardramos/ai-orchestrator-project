#!/usr/bin/env python3
"""
Start the AI Orchestrator HTTP server with admin UI.

Usage:
    python scripts/start_server.py [--port PORT] [--host HOST]
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools_catalog.api.http_server import HttpServerTool
from src.plugins.loader import _load_bootstrap


def main():
    parser = argparse.ArgumentParser(description="Start AI Orchestrator HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    args = parser.parse_args()

    bootstrap = _load_bootstrap("config/bootstrap.yaml")
    redis_url = bootstrap.get("redis_url", os.environ.get("REDIS_URL", "redis://localhost:6379"))

    config = {
        "host": args.host,
        "port": args.port,
        "redis_url": redis_url,
        "api_key": os.environ.get("HTTP_API_KEY", ""),
    }

    async def run():
        tool = HttpServerTool()
        tool.initialize(config)

        def on_task(envelope):
            print(f"[Task] {envelope.id}: {envelope.task_description[:60]}...")

        print(f"\n  AI Orchestrator Server")
        print(f"  ========================")
        print(f"  Dashboard:  http://{args.host}:{args.port}/ui/")
        print(f"  API:        http://{args.host}:{args.port}/api/tools")
        print(f"  Health:     http://{args.host}:{args.port}/api/status")
        print(f"\n  Press Ctrl+C to stop\n")

        await tool.start_listener(on_task)
        await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
