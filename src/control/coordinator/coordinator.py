from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import time

app = FastAPI(title="Coordinator Service")

class Heartbeat(BaseModel):
    worker_id: str
    timestamp: float = None
    status: str = "alive"

@app.post("/heartbeat")
async def receive_heartbeat(hb: Heartbeat):
    # In a real system, this would update a shared state or DB
    hb.timestamp = hb.timestamp or time.time()
    return {"received": True, "worker_id": hb.worker_id, "timestamp": hb.timestamp}

# Endpoint for CNC to query aggregated health (placeholder)
@app.get("/health")
async def health_report():
    # Placeholder static response
    return {"status": "ok", "message": "Coordinator health good"}
