from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import subprocess
import json

app = FastAPI(title="Scaler Service")

# Simple scaling via Docker Compose (for single-server) or kubectl (for k8s)
# This is a placeholder implementation; in production you would integrate with the orchestrator API.

class ScaleRequest(BaseModel):
    service_name: str
    replicas: int

def run_compose_scale(service: str, replicas: int):
    cmd = ["docker", "compose", "up", "-d", f"--scale", f"{service}={replicas}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Compose scaling failed: {result.stderr}")
    return result.stdout

@app.post("/scale")
async def scale_service(req: ScaleRequest):
    try:
        output = run_compose_scale(req.service_name, req.replicas)
        return {"status": "scaled", "service": req.service_name, "replicas": req.replicas, "output": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
