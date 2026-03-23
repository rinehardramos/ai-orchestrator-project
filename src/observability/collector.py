"""
Observability Collector (Simplified)
====================================
Polls cluster data sources every POLL_INTERVAL seconds and publishes events to Redis pub/sub.
Prometheus metrics removed in Phase 2 — Opik now handles LLM tracing.

Data sources:
  - Docker daemon (container CPU/mem/status)
  - Temporal API (workflow counts, latency)
  - Cluster nodes from config/cluster_nodes.yaml
  - L1 Redis, L2 Qdrant, L3 S3 performance probes
"""

import asyncio
import json
import os
import socket
import time
from datetime import datetime
from typing import Any

import httpx
import yaml

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
S3_BUCKET = os.getenv("S3_ARCHIVE_BUCKET")
NODES_FILE = os.path.join(os.path.dirname(__file__), "../../config/cluster_nodes.yaml")


def load_nodes() -> list[dict]:
    try:
        with open(NODES_FILE) as f:
            return yaml.safe_load(f).get("nodes", [])
    except Exception:
        return [{"name": "local", "host": "localhost", "role": "genesis"}]


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


async def probe_nodes(nodes: list[dict]) -> list[dict]:
    results = []
    for n in nodes:
        host = n.get("host", "localhost")
        role = n.get("role", "execution")
        name = n.get("name", host)
        is_up = tcp_reachable(host, 22) or host == "localhost"
        results.append({
            "name": name, "host": host, "role": role,
            "up": is_up, "ts": datetime.utcnow().isoformat()
        })
    return results


async def collect_docker_stats(node_name: str = "local") -> list[dict]:
    stats = []
    try:
        import docker
        client = docker.from_env()
        for container in client.containers.list():
            try:
                raw = container.stats(stream=False)
                cpu_delta = raw["cpu_stats"]["cpu_usage"]["total_usage"] - \
                            raw["precpu_stats"]["cpu_usage"]["total_usage"]
                sys_delta = raw["cpu_stats"]["system_cpu_usage"] - \
                           raw["precpu_stats"]["system_cpu_usage"]
                num_cpu = raw["cpu_stats"]["online_cpus"]
                cpu_pct = (cpu_delta / sys_delta) * num_cpu * 100.0 if sys_delta > 0 else 0
                mem_mb = raw["memory_stats"].get("usage", 0) / 1024 / 1024
                stats.append({"name": container.name, "cpu_pct": cpu_pct, "mem_mb": mem_mb})
            except Exception:
                pass
    except Exception:
        pass
    return stats


async def collect_temporal() -> dict[str, Any]:
    data = {"active": 0, "failed": 0, "tasks": []}
    try:
        from temporalio.client import Client
        client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=3.0)
        active = 0
        async for wf in client.list_workflows("ExecutionStatus='Running'"):
            active += 1
        
        failed = 0
        try:
            async for wf in client.list_workflows("ExecutionStatus='Failed'"):
                failed += 1
        except Exception:
            pass
        
        data["active"] = active
        data["failed"] = failed
        
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        tasks = []
        try:
            async for wf in client.list_workflows('WorkflowType="AIOrchestrationWorkflow"'):
                status_val = wf.status
                status_str = status_val.name if hasattr(status_val, 'name') else str(status_val)
                if status_str == "1": status_str = "RUNNING"
                elif status_str == "2": status_str = "COMPLETED"
                elif status_str == "3": status_str = "FAILED"
                elif status_str == "4": status_str = "CANCELED"
                elif status_str == "7": status_str = "TIMED_OUT"
                
                desc = await r.get(f"obs:task_desc:{wf.id}")
                tasks.append({
                    "task_id": wf.id,
                    "status": status_str,
                    "description": desc or "No description available",
                    "time": wf.start_time.isoformat() if wf.start_time else None
                })
                if len(tasks) >= 15:
                    break
        except Exception as query_e:
            print(f"[Collector] Error querying Temporal task history: {query_e}")
        finally:
            await r.aclose()
        
        data["tasks"] = tasks
    except Exception as e:
        print(f"[Collector] Temporal probe error: {e}")
    return data


async def collect_l1_redis() -> dict[str, Any]:
    start = time.time()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        latency = time.time() - start
        await r.aclose()
        return {"latency_ms": round(latency * 1000, 2), "status": "online"}
    except Exception:
        return {"latency_ms": -1, "status": "offline"}


async def collect_l2_qdrant() -> dict[str, Any]:
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{QDRANT_URL}/healthz")
            latency = time.time() - start
            if resp.status_code == 200:
                return {"latency_ms": round(latency * 1000, 2), "status": "online"}
    except Exception:
        pass
    return {"latency_ms": -1, "status": "offline"}


async def collect_l3_s3() -> dict[str, Any]:
    if not S3_BUCKET:
        return {"latency_ms": 0, "status": "unconfigured"}
    start = time.time()
    try:
        import boto3
        from botocore.config import Config
        s3 = boto3.client('s3', config=Config(retries={'max_attempts': 0}, connect_timeout=1, read_timeout=1))
        s3.head_bucket(Bucket=S3_BUCKET)
        latency = time.time() - start
        return {"latency_ms": round(latency * 1000, 2), "status": "online"}
    except Exception:
        return {"latency_ms": -1, "status": "offline"}


async def publish_to_redis(event: dict):
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.publish("obs:events", json.dumps(event))
        await r.aclose()
    except Exception:
        pass


async def run_collector():
    print(f"[Collector] Starting — poll every {POLL_INTERVAL}s (Prometheus removed, use Opik for LLM tracing)")
    nodes = load_nodes()

    while True:
        tick_start = time.time()
        try:
            results = await asyncio.gather(
                probe_nodes(nodes),
                collect_docker_stats("local"),
                collect_temporal(),
                collect_l1_redis(),
                collect_l2_qdrant(),
                collect_l3_s3(),
                return_exceptions=True,
            )
            
            node_results = results[0] if not isinstance(results[0], Exception) else []
            docker_stats = results[1] if not isinstance(results[1], Exception) else []
            temporal = results[2] if not isinstance(results[2], Exception) else {}
            l1 = results[3] if not isinstance(results[3], Exception) else {"status": "error"}
            l2 = results[4] if not isinstance(results[4], Exception) else {"status": "error"}
            l3 = results[5] if not isinstance(results[5], Exception) else {"status": "error"}

            event = {
                "ts": datetime.utcnow().isoformat(),
                "nodes": node_results,
                "containers": docker_stats,
                "temporal": temporal,
                "performance": {
                    "l1_redis": l1,
                    "l2_qdrant": l2,
                    "l3_s3": l3
                }
            }
            await publish_to_redis(event)
            elapsed = time.time() - tick_start
            print(f"[Collector] tick OK ({elapsed:.2f}s) | "
                  f"nodes={len(event['nodes'])} "
                  f"workflows={event['temporal'].get('active', '?')} "
                  f"containers={len(event['containers'])}")
        except Exception as e:
            print(f"[Collector] tick error: {e}")

        await asyncio.sleep(max(0, POLL_INTERVAL - (time.time() - tick_start)))


if __name__ == "__main__":
    asyncio.run(run_collector())
