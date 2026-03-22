"""
Health Check Service - Minimal service status monitoring.
Probes critical infrastructure services and reports status via logs and optional HTTP endpoint.
"""
import asyncio
import socket
import time
import os
from datetime import datetime
from typing import Any

import httpx
import yaml


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
NODES_FILE = os.path.join(os.path.dirname(__file__), "../../config/cluster_nodes.yaml")


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


async def check_redis() -> dict[str, Any]:
    start = time.time()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        latency = time.time() - start
        await r.aclose()
        return {"status": "online", "latency_ms": round(latency * 1000, 2)}
    except Exception as e:
        return {"status": "offline", "error": str(e)}


async def check_temporal() -> dict[str, Any]:
    start = time.time()
    try:
        from temporalio.client import Client
        host, port = TEMPORAL_HOST.split(":") if ":" in TEMPORAL_HOST else (TEMPORAL_HOST, "7233")
        if not tcp_reachable(host, int(port), timeout=3.0):
            return {"status": "offline", "error": "TCP connection failed"}
        
        client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=5.0)
        latency = time.time() - start
        return {"status": "online", "latency_ms": round(latency * 1000, 2)}
    except Exception as e:
        return {"status": "offline", "error": str(e)}


async def check_qdrant() -> dict[str, Any]:
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{QDRANT_URL}/healthz")
            latency = time.time() - start
            if resp.status_code == 200:
                return {"status": "online", "latency_ms": round(latency * 1000, 2)}
            return {"status": "degraded", "code": resp.status_code}
    except Exception as e:
        return {"status": "offline", "error": str(e)}


def load_nodes() -> list[dict]:
    try:
        with open(NODES_FILE) as f:
            return yaml.safe_load(f).get("nodes", [])
    except Exception:
        return [{"name": "local", "host": "localhost", "role": "cnc"}]


async def probe_nodes(nodes: list[dict]) -> list[dict]:
    results = []
    for n in nodes:
        host = n.get("host", "localhost")
        role = n.get("role", "unknown")
        name = n.get("name", host)
        is_up = tcp_reachable(host, 22) or host == "localhost"
        results.append({
            "name": name,
            "host": host,
            "role": role,
            "status": "up" if is_up else "down",
            "ts": datetime.utcnow().isoformat()
        })
    return results


async def run_health_check(interval: int = 30) -> dict[str, Any]:
    nodes = load_nodes()
    
    results = await asyncio.gather(
        check_redis(),
        check_temporal(),
        check_qdrant(),
        probe_nodes(nodes),
        return_exceptions=True,
    )
    
    redis_result = results[0] if not isinstance(results[0], Exception) else {"status": "error"}
    temporal_result = results[1] if not isinstance(results[1], Exception) else {"status": "error"}
    qdrant_result = results[2] if not isinstance(results[2], Exception) else {"status": "error"}
    nodes_result = results[3] if not isinstance(results[3], Exception) else []
    
    return {
        "ts": datetime.utcnow().isoformat(),
        "services": {
            "redis": redis_result,
            "temporal": temporal_result,
            "qdrant": qdrant_result,
        },
        "nodes": nodes_result,
    }


async def health_loop(interval: int = 30):
    print(f"[HealthCheck] Starting — interval: {interval}s")
    while True:
        try:
            status = await run_health_check(interval)
            
            services = status["services"]
            nodes_up = sum(1 for n in status["nodes"] if n.get("status") == "up")
            nodes_total = len(status["nodes"])
            
            print(
                f"[HealthCheck] "
                f"redis={services['redis']['status']} "
                f"temporal={services['temporal']['status']} "
                f"qdrant={services['qdrant']['status']} "
                f"nodes={nodes_up}/{nodes_total}"
            )
        except Exception as e:
            print(f"[HealthCheck] Error: {e}")
        
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(health_loop())
