"""
Observability Web Server
FastAPI backend with WebSocket push from Redis pub/sub.
Access at: http://localhost:9090
"""

import asyncio
import json
import os
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")
COLLECTOR_STATE: dict = {}   # last snapshot from collector

app = FastAPI(title="AI Orchestrator — Observability")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── REST endpoints ─────────────────────────────────────────────────────────

@app.get("/api/nodes")
async def get_nodes():
    return COLLECTOR_STATE.get("nodes", [])

@app.get("/api/workflows")
async def get_workflows():
    return COLLECTOR_STATE.get("temporal", {})

@app.get("/api/metrics")
async def get_metrics():
    return {
        "containers": COLLECTOR_STATE.get("containers", []),
        "model_sel":  COLLECTOR_STATE.get("model_sel", {}),
        "coordinator":COLLECTOR_STATE.get("coordinator", {}),
    }

@app.get("/api/snapshot")
async def get_snapshot():
    return COLLECTOR_STATE

@app.get("/health")
async def health():
    return {"status": "ok"}

# ── WebSocket — live event stream ──────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await manager.connect(websocket)
    # Send current snapshot immediately on connect
    if COLLECTOR_STATE:
        await websocket.send_text(json.dumps(COLLECTOR_STATE))
    try:
        while True:
            await asyncio.sleep(30)  # keep-alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ── Redis subscriber (broadcasts to WebSocket clients) ─────────────────────

async def redis_subscriber():
    """Background task — subscribes to obs:events and pushes to WebSocket clients."""
    global COLLECTOR_STATE
    while True:
        try:
            r = aioredis.from_url(REDIS_URL)
            pubsub = r.pubsub()
            await pubsub.subscribe("obs:events")
            print("[Web] Subscribed to Redis obs:events")
            
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    raw = message["data"].decode("utf-8")
                    COLLECTOR_STATE = json.loads(raw)
                    await manager.broadcast(raw)
                await asyncio.sleep(0.1)  # avoid CPU spin
        except Exception as e:
            print(f"[Web] Redis subscriber error: {e} — retrying in 5s")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup():
    asyncio.create_task(redis_subscriber())

# ── Root — serve dashboard ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return (STATIC_DIR / "index.html").read_text()
