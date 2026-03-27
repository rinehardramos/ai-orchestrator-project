"""
Web UI Server - Standalone entry point.

Usage:
    uvicorn src.web.server:app --host 0.0.0.0 --port 8000
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import FastAPI
from src.web.admin import create_admin_router
from src.web.api.internal import internal_router

app = FastAPI(
    title="AI Orchestrator Admin",
    description="Web UI for managing AI Orchestrator",
    version="1.0.0",
)

app.include_router(create_admin_router())
app.include_router(internal_router)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "AI Orchestrator Web UI",
        "ui": "/ui/",
        "api_docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
