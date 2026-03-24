import asyncio
import time
from typing import Dict, Any, List
from fastapi import APIRouter

status_router = APIRouter(prefix="/api")

CHECK_TIMEOUT = 3.0


async def check_tcp(host: str, port: int) -> Dict[str, Any]:
    try:
        start = time.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=CHECK_TIMEOUT
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "up", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def check_redis(host: str, port: int) -> Dict[str, Any]:
    try:
        import redis.asyncio as aioredis
        start = time.time()
        client = aioredis.from_url(f"redis://{host}:{port}")
        await client.ping()
        await client.close()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "up", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "down", "error": str(e)}


def load_settings():
    import yaml
    import os
    path = "config/settings.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


@status_router.get("/status")
async def get_status() -> Dict[str, Any]:
    settings = load_settings()
    active_env = settings.get("active_environment", "primary")
    env_config = settings.get("environments", {}).get(active_env, {})
    
    results = {}
    
    tasks = []
    keys = []
    
    temporal = env_config.get("temporal", {})
    if temporal:
        tasks.append(check_tcp(temporal.get("host", "localhost"), temporal.get("port", 7233)))
        keys.append("temporal")
    
    qdrant = env_config.get("qdrant", {})
    if qdrant:
        tasks.append(check_tcp(qdrant.get("host", "localhost"), qdrant.get("port", 6333)))
        keys.append("qdrant")
    
    redis = env_config.get("redis", {})
    if redis:
        tasks.append(check_redis(redis.get("host", "localhost"), redis.get("port", 6379)))
        keys.append("redis")
    
    lmstudio = env_config.get("lmstudio", {})
    if lmstudio:
        tasks.append(check_tcp(lmstudio.get("host", "localhost"), lmstudio.get("port", 1234)))
        keys.append("lmstudio")
    
    if tasks:
        check_results = await asyncio.gather(*tasks)
        for key, result in zip(keys, check_results):
            results[key] = result
    
    workers = []
    import os
    cluster_path = "config/cluster_nodes.yaml"
    if os.path.exists(cluster_path):
        import yaml
        with open(cluster_path, "r") as f:
            cluster_data = yaml.safe_load(f) or {}
        for node in cluster_data.get("nodes", []):
            if node.get("role") == "execution":
                worker_status = await check_tcp(
                    node.get("host", "localhost"),
                    node.get("port", 22)
                )
                workers.append({
                    "name": node.get("name", "unknown"),
                    "host": node.get("host", ""),
                    **worker_status
                })
    
    results["workers"] = workers
    
    return results
