"""
Integration Test: End-to-End Live System Task Execution
========================================================
Run this test ONLY when a live Control Plane + Execution Plane is running.

Requirements:
  - Temporal Server reachable at TEMPORAL_HOST_URL (default: localhost:7233)
  - At least one worker running: python src/execution/worker/worker.py
  - (Optional) Dispatcher service running: uvicorn src.control.dispatcher.dispatcher:app

Skip behaviour:
  - If Temporal is not reachable, all tests in this module are automatically skipped.

Usage:
  PYTHONPATH=. python3 -m pytest tests/test_integration_live.py -v -s

Environment variables (override via .env or shell):
  TEMPORAL_HOST_URL   - Temporal server address (default: localhost:7233)
  TEST_LLM_PROVIDER   - LLM provider to use (default: google)
  TEST_LLM_MODEL      - Model ID             (default: gemini-2.0-flash)
  TEST_TASK           - Task description     (default: built-in smoke test)
  DISPATCHER_URL      - Dispatcher service URL (default: http://localhost:8001)
  TEST_TIMEOUT_SEC    - Max seconds to wait for workflow (default: 120)
"""

import asyncio
import os
import socket
import uuid
import time
import pytest
import httpx

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_env(path=".env"):
    """Minimal .env loader — no dependencies."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

_load_env()

TEMPORAL_HOST    = os.environ.get("TEMPORAL_HOST_URL", "localhost:7233")
DISPATCHER_URL   = os.environ.get("DISPATCHER_URL", "http://localhost:8001")
LLM_PROVIDER     = os.environ.get("TEST_LLM_PROVIDER", "google")
LLM_MODEL        = os.environ.get("TEST_LLM_MODEL", "gemini-2.0-flash")
TEST_TASK        = os.environ.get("TEST_TASK", "Run a quick smoke test: summarize the number 42 in one sentence.")
TEST_TIMEOUT_SEC = int(os.environ.get("TEST_TIMEOUT_SEC", "300"))
TASK_QUEUE       = "ai-orchestration-queue"


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


def _parse_temporal_host():
    """Split 'host:port' string into (host, int port)."""
    parts = TEMPORAL_HOST.split(":")
    return parts[0], int(parts[1]) if len(parts) > 1 else 7233


# ─── Pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_live_temporal():
    """Skip the entire module if Temporal is unreachable."""
    host, port = _parse_temporal_host()
    if not _tcp_reachable(host, port):
        pytest.skip(
            f"[SKIP] Temporal not reachable at {TEMPORAL_HOST}. "
            "Start the Control Plane and a Worker, then re-run."
        )


@pytest.fixture(scope="session")
def temporal_client():
    """Create and return a live Temporal client (session-scoped)."""
    try:
        from temporalio.client import Client
    except ImportError:
        pytest.skip("temporalio not installed — run inside the project virtualenv or Docker.")

    async def _connect():
        return await Client.connect(TEMPORAL_HOST)

    return asyncio.get_event_loop().run_until_complete(_connect())


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestControlPlaneConnectivity:
    """Pre-flight checks — validate the live system topology."""

    def test_temporal_is_reachable(self):
        host, port = _parse_temporal_host()
        assert _tcp_reachable(host, port), f"Temporal not reachable at {host}:{port}"
        print(f"\n  ✅ Temporal reachable at {host}:{port}")

    def test_dispatcher_service_is_up(self):
        """Best-effort: skip if Dispatcher isn't running."""
        try:
            resp = httpx.get(f"{DISPATCHER_URL}/docs", timeout=3)
            assert resp.status_code == 200
            print(f"\n  ✅ Dispatcher service up at {DISPATCHER_URL}")
        except Exception:
            pytest.skip(f"Dispatcher not running at {DISPATCHER_URL} — skipping dispatcher check.")


class TestDispatcherRouting:
    """Submit a task to the Dispatcher and verify it routes correctly."""

    def test_dispatch_task_to_correct_pool(self):
        try:
            payload = {
                "task_id": f"integ-{uuid.uuid4()}",
                "type": "nlp",
                "priority": 1,
                "payload": {"text": TEST_TASK}
            }
            resp = httpx.post(f"{DISPATCHER_URL}/dispatch", json=payload, timeout=5)
            assert resp.status_code == 200, f"Dispatcher returned {resp.status_code}: {resp.text}"
            data = resp.json()
            assert "dispatched_to" in data
            assert data["task_id"] == payload["task_id"]
            print(f"\n  ✅ Task routed to pool: {data['dispatched_to']}")
        except httpx.ConnectError:
            pytest.skip("Dispatcher not reachable — skipping routing test.")


class TestEndToEndWorkflow:
    """
    Full integration test:
    1. Submit an AIOrchestrationWorkflow to Temporal
    2. Poll for progress heartbeats from the Execution Plane worker
    3. Assert the workflow completes successfully
    """

    def test_live_task_execution_and_monitoring(self, temporal_client):
        workflow_id = f"integ-e2e-{uuid.uuid4()}"
        print(f"\n  📤 Submitting workflow: {workflow_id}")
        print(f"     Task   : {TEST_TASK}")
        print(f"     Model  : {LLM_MODEL} ({LLM_PROVIDER})")
        print(f"     Queue  : {TASK_QUEUE}")
        print(f"     Timeout: {TEST_TIMEOUT_SEC}s")

        asyncio.get_event_loop().run_until_complete(
            _run_and_monitor(temporal_client, workflow_id)
        )


async def _run_and_monitor(client, workflow_id: str):
    from temporalio.client import WorkflowExecutionStatus

    # Detect worker signature from env — default to new 3-arg signature, fallback to legacy 1-arg
    use_legacy_worker = os.environ.get("LEGACY_WORKER", "0") == "1"

    if use_legacy_worker:
        # Old central_node/worker.py: run(self, task: str)
        handle = await client.start_workflow(
            "AIOrchestrationWorkflow",
            args=[TEST_TASK],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    else:
        # New src/execution/worker/worker.py: run(self, task, model_id, provider)
        handle = await client.start_workflow(
            "AIOrchestrationWorkflow",
            args=[TEST_TASK, LLM_MODEL, LLM_PROVIDER],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    print(f"\n  🚀 Workflow started. Monitoring execution...")

    # 2. Poll for progress
    start = time.time()
    last_progress = None
    while True:
        elapsed = time.time() - start
        if elapsed > TEST_TIMEOUT_SEC:
            pytest.fail(
                f"Workflow {workflow_id} did not complete within {TEST_TIMEOUT_SEC}s. "
                "Check that a worker is running and connected."
            )

        desc = await handle.describe()

        # Print heartbeat progress from the Execution Plane worker
        if desc.raw_description.pending_activities:
            act = desc.raw_description.pending_activities[0]
            if act.heartbeat_details:
                try:
                    from temporalio.converter import default as _default_converter
                    payloads = act.heartbeat_details.payloads
                    progress = _default_converter().payload_converter.from_payloads(payloads)[0]
                    if progress != last_progress:
                        print(f"  📈 Worker progress: {progress}  [{elapsed:.0f}s elapsed]")
                        last_progress = progress
                except Exception:
                    pass

        if desc.status != WorkflowExecutionStatus.RUNNING:
            break

        await asyncio.sleep(2.0)

    # 3. Assert success
    assert desc.status == WorkflowExecutionStatus.COMPLETED, (
        f"Workflow ended with status: {desc.status.name}"
    )

    result = await handle.result()
    print(f"\n  ✅ Workflow COMPLETED in {time.time() - start:.1f}s")
    print(f"     Status       : {result.get('status', 'N/A')}")
    print(f"     Assessment   : {str(result.get('assessment', ''))[:200]}...")

    assert result.get("status") == "completed", f"Unexpected result status: {result}"
    if "summary" in result:
        assert "summary" in result, "Result missing 'summary' field"
    else:
        assert "assessment" in result, "Result missing 'assessment' field"
        assert "recommendations" in result, "Result missing 'recommendations' field"
