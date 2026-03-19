"""
Observability Collector
=======================
Polls all cluster data sources every POLL_INTERVAL seconds and:
  - Exposes a Prometheus /metrics endpoint
  - Publishes events to Redis pub/sub channel 'obs:events'

Data sources:
  - Docker daemon (container CPU/mem/status per node via SSH or local)
  - Temporal API (workflow counts, latency)
  - Coordinator /heartbeat (worker health)
  - Model Selector /status (LLM providers)
  - Cluster nodes from config/cluster_nodes.yaml
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
from prometheus_client import Counter, Gauge, Histogram, start_http_server, REGISTRY

def _gauge(name, doc, labels=()):
    try:
        return Gauge(name, doc, labels)
    except ValueError:   # already registered (hot-reload)
        return REGISTRY._names_to_collectors.get(name)

def _counter(name, doc, labels=()):
    try:
        return Counter(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)

def _histogram(name, doc, labels=()):
    try:
        return Histogram(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)

NODE_UP          = _gauge("node_up",                "Node reachability (1=up)",  ["node", "role"])
WORKFLOW_ACTIVE  = _gauge("workflow_active_total",  "Running Temporal workflows")
WORKFLOW_FAILED  = _counter("workflow_failed_total","Failed Temporal workflows")
WORKER_TASKS     = _gauge("worker_task_count",      "Tasks handled by worker",   ["worker_id"])
LLM_TOKENS       = _counter("model_tokens_used_total","LLM tokens used",         ["provider", "model"])
LLM_LATENCY      = _histogram("model_latency_seconds","LLM call latency",        ["provider", "model"])
TEMPORAL_LATENCY = _histogram("temporal_api_latency_seconds", "Temporal API call latency")
REPLICAS         = _gauge("worker_replicas",        "Container replicas",        ["pool"])
CONTAINER_CPU    = _gauge("container_cpu_percent",  "Container CPU %",           ["name", "node"])
CONTAINER_MEM    = _gauge("container_mem_mb",       "Container memory MB",       ["name", "node"])
COLLECTOR_ERRORS = _counter("collector_errors_total","Collector probe errors",   ["source"])

# ── Performance Metrics (L1, L2, L3) ──────────────────────────────────────────
L1_LATENCY       = _histogram("l1_redis_latency_seconds", "Redis L1 access latency")
L2_LATENCY       = _histogram("l2_qdrant_latency_seconds", "Qdrant L2 access latency")
L3_LATENCY       = _histogram("l3_s3_latency_seconds", "S3 L3 access latency")

# ── Config ────────────────────────────────────────────────────────────────────

POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL", "10"))
PROMETHEUS_PORT  = int(os.getenv("PROMETHEUS_PORT", "9091"))
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")
TEMPORAL_HOST    = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
COORDINATOR_URL  = os.getenv("COORDINATOR_URL", "http://localhost:8000")
MODEL_SEL_URL    = os.getenv("MODEL_SELECTOR_URL", "http://localhost:8003")
QDRANT_URL       = os.getenv("QDRANT_URL", "http://localhost:6333")
S3_BUCKET        = os.getenv("S3_ARCHIVE_BUCKET")
NODES_FILE       = os.path.join(os.path.dirname(__file__), "../../config/cluster_nodes.yaml")

# ── Node loader ────────────────────────────────────────────────────────────────

def load_nodes() -> list[dict]:
    try:
        with open(NODES_FILE) as f:
            return yaml.safe_load(f).get("nodes", [])
    except Exception:
        return [{"name": "local", "host": "localhost", "role": "cnc"}]

# ── TCP connectivity probe ────────────────────────────────────────────────────

def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False

# ── Node health probes ────────────────────────────────────────────────────────

async def probe_nodes(nodes: list[dict]) -> list[dict]:
    results = []
    for n in nodes:
        host = n.get("host", "localhost")
        role = n.get("role", "execution")
        name = n.get("name", host)
        is_up = tcp_reachable(host, 22) or host == "localhost"
        NODE_UP.labels(node=name, role=role).set(1 if is_up else 0)
        results.append({
            "name": name, "host": host, "role": role,
            "up": is_up, "ts": datetime.utcnow().isoformat()
        })
    return results

# ── Docker stats (local) ──────────────────────────────────────────────────────

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
                sys_delta  = raw["cpu_stats"]["system_cpu_usage"] - \
                             raw["precpu_stats"]["system_cpu_usage"]
                num_cpu    = raw["cpu_stats"]["online_cpus"]
                cpu_pct    = (cpu_delta / sys_delta) * num_cpu * 100.0 if sys_delta > 0 else 0
                mem_mb     = raw["memory_stats"].get("usage", 0) / 1024 / 1024
                name       = container.name
                CONTAINER_CPU.labels(name=name, node=node_name).set(round(cpu_pct, 2))
                CONTAINER_MEM.labels(name=name, node=node_name).set(round(mem_mb, 2))
                stats.append({"name": name, "cpu_pct": cpu_pct, "mem_mb": mem_mb})
            except Exception:
                pass
    except Exception as e:
        COLLECTOR_ERRORS.labels(source="docker").inc()
    return stats

# ── Temporal probe ────────────────────────────────────────────────────────────

async def collect_temporal() -> dict[str, Any]:
    data = {"active": 0, "failed": 0, "tasks": []}
    try:
        start_t = time.time()
        from temporalio.client import Client, WorkflowExecutionStatus
        client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=3.0)
        active = 0
        async for wf in client.list_workflows("ExecutionStatus='Running'"):
            active += 1
            
        # Get tasks with ID, status, and fetch description from Redis
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        tasks = []
        try:
            async for wf in client.list_workflows('WorkflowType="AIOrchestrationWorkflow"'):
                # Extract status as string, e.g., 'COMPLETED', 'RUNNING'
                status_str = str(wf.status).split('.')[-1]
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
            
        WORKFLOW_ACTIVE.set(active)
        TEMPORAL_LATENCY.observe(time.time() - start_t)
        data["active"] = active
        data["tasks"] = tasks
    except Exception as e:
        COLLECTOR_ERRORS.labels(source="temporal").inc()
    return data

# ── Coordinator probe ─────────────────────────────────────────────────────────

async def collect_coordinator() -> dict[str, Any]:
    data = {"workers": []}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{COORDINATOR_URL}/heartbeat")
            if resp.status_code == 200:
                body = resp.json()
                workers = body.get("workers", [])
                for w in workers:
                    wid = w.get("worker_id", "unknown")
                    tasks = w.get("tasks_handled", 0)
                    WORKER_TASKS.labels(worker_id=wid).set(tasks)
                data["workers"] = workers
    except Exception:
        COLLECTOR_ERRORS.labels(source="coordinator").inc()
    return data

# ── Model Selector probe ──────────────────────────────────────────────────────

async def collect_model_selector() -> dict[str, Any]:
    data = {"providers": []}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{MODEL_SEL_URL}/status")
            if resp.status_code == 200:
                body = resp.json()
                data["providers"] = body.get("active_providers", [])
    except Exception:
        COLLECTOR_ERRORS.labels(source="model_selector").inc()
    return data

# ── L1, L2, L3 Performance Probes ─────────────────────────────────────────────

async def collect_l1_redis() -> dict[str, Any]:
    start = time.time()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        latency = time.time() - start
        L1_LATENCY.observe(latency)
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
                L2_LATENCY.observe(latency)
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
        # Simple head_bucket to check connectivity/latency
        s3.head_bucket(Bucket=S3_BUCKET)
        latency = time.time() - start
        L3_LATENCY.observe(latency)
        return {"latency_ms": round(latency * 1000, 2), "status": "online"}
    except Exception:
        return {"latency_ms": -1, "status": "offline"}

# ── Redis publisher ───────────────────────────────────────────────────────────

async def publish_to_redis(event: dict):
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.publish("obs:events", json.dumps(event))
        await r.aclose()
    except Exception:
        pass  # best-effort — Redis may not always be available

# ── Main poll loop ────────────────────────────────────────────────────────────

async def run_collector():
    print(f"[Collector] Starting — Prometheus on :{PROMETHEUS_PORT}, poll every {POLL_INTERVAL}s")
    start_http_server(PROMETHEUS_PORT)
    nodes = load_nodes()

    while True:
        tick_start = time.time()
        try:
            results = await asyncio.gather(
                probe_nodes(nodes),
                collect_docker_stats("local"),
                collect_temporal(),
                collect_coordinator(),
                collect_model_selector(),
                collect_l1_redis(),
                collect_l2_qdrant(),
                collect_l3_s3(),
                return_exceptions=True,
            )
            
            # Map results safely
            node_results = results[0] if not isinstance(results[0], Exception) else []
            docker_stats = results[1] if not isinstance(results[1], Exception) else []
            temporal     = results[2] if not isinstance(results[2], Exception) else {}
            coordinator  = results[3] if not isinstance(results[3], Exception) else {}
            model_sel    = results[4] if not isinstance(results[4], Exception) else {}
            l1           = results[5] if not isinstance(results[5], Exception) else {"status": "error"}
            l2           = results[6] if not isinstance(results[6], Exception) else {"status": "error"}
            l3           = results[7] if not isinstance(results[7], Exception) else {"status": "error"}

            event = {
                "ts": datetime.utcnow().isoformat(),
                "nodes":      node_results,
                "containers": docker_stats,
                "temporal":   temporal,
                "coordinator": coordinator,
                "model_sel":  model_sel,
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
