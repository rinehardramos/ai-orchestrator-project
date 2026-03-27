"""
Mercenary Marketplace API Entry Point.

Isolated service for bounty-based AI agent marketplace.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from src.mercenary.config import config
from src.mercenary.api import auth_router, bounties_router, agents_router, wallet_router
from src.mercenary.db.connection import init_database, seed_agents

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agent Mercenaries Marketplace",
    description="Create bounties and AI agents will complete them for you",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(bounties_router)
app.include_router(agents_router)
app.include_router(wallet_router)


@app.on_event("startup")
async def startup_event():
    logger.info("Initializing mercenary database...")
    init_database()
    logger.info("Seeding agents...")
    seed_agents()
    logger.info(f"Mercenary API ready on {config.API_HOST}:{config.API_PORT}")


@app.get("/")
async def root():
    return {
        "service": "Agent Mercenaries Marketplace",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.mercenary.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True
    )
