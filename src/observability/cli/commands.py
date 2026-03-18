"""
Observability CLI — one-shot commands.
Run inside the project:
  PYTHONPATH=. python -m src.observability.cli status
  PYTHONPATH=. python -m src.observability.cli nodes
  PYTHONPATH=. python -m src.observability.cli workflows
  PYTHONPATH=. python -m src.observability.cli containers
  PYTHONPATH=. python -m src.observability.cli logs [--follow]
  PYTHONPATH=. python -m src.observability.cli watch    # live Textual TUI
"""

import asyncio
import json
import os
import socket
import sys
import time
from datetime import datetime

import click
import yaml

# ── Config ────────────────────────────────────────────────────────────────────
REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6380")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
NODES_FILE    = os.path.join(os.path.dirname(__file__), "../../../config/cluster_nodes.yaml")


def load_nodes():
    try:
        with open(NODES_FILE) as f:
            return yaml.safe_load(f).get("nodes", [])
    except Exception:
        return []


def tcp_up(host, port=22, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def docker_stats():
    try:
        import docker
        c = docker.from_env()
        rows = []
        for ct in c.containers.list():
            try:
                raw = ct.stats(stream=False)
                cpu_d = raw["cpu_stats"]["cpu_usage"]["total_usage"] - \
                        raw["precpu_stats"]["cpu_usage"]["total_usage"]
                sys_d = raw["cpu_stats"]["system_cpu_usage"] - \
                        raw["precpu_stats"]["system_cpu_usage"]
                ncpu  = raw["cpu_stats"].get("online_cpus", 1)
                cpu   = (cpu_d / sys_d) * ncpu * 100 if sys_d > 0 else 0
                mem   = raw["memory_stats"].get("usage", 0) / 1024 / 1024
                rows.append({"name": ct.name, "status": ct.status,
                             "cpu": cpu, "mem": mem})
            except Exception:
                pass
        return rows
    except Exception as e:
        return []


async def temporal_count():
    try:
        from temporalio.client import Client
        client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=3.0)
        count = 0
        async for _ in client.list_workflows("ExecutionStatus='Running'"):
            count += 1
        return count
    except Exception:
        return None


# ── Click CLI ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """AI Orchestrator — Cluster CLI Monitor"""


@cli.command()
def status():
    """Quick cluster status overview."""
    nodes = load_nodes()
    click.echo("\n╔══════════════════════════════════════╗")
    click.echo("║  AI Orchestrator — Cluster Status    ║")
    click.echo(f"║  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}               ║")
    click.echo("╚══════════════════════════════════════╝\n")

    # Nodes
    click.echo("🌐  NODES")
    for n in nodes:
        host = n.get("host", "localhost")
        role = n.get("role", "?")
        name = n.get("name", host)
        up   = tcp_up(host) or host == "localhost"
        dot  = click.style("●", fg="green") if up else click.style("○", fg="red")
        state = click.style("UP  ", fg="green") if up else click.style("DOWN", fg="red")
        click.echo(f"  {dot} {name:<30} {state}  [{role}]  {host}")

    # Temporal
    click.echo("\n⚙️   TEMPORAL")
    count = asyncio.run(temporal_count())
    if count is None:
        click.echo(f"  {click.style('UNREACHABLE', fg='yellow')}  ({TEMPORAL_HOST})")
    else:
        click.echo(f"  {click.style(str(count), fg='cyan')} active workflow(s)")

    # Containers
    click.echo("\n🐳  LOCAL CONTAINERS")
    rows = docker_stats()
    if not rows:
        click.echo("  (no containers or Docker not accessible)")
    for r in rows:
        cpu_color = "green" if r["cpu"] < 50 else "yellow" if r["cpu"] < 80 else "red"
        cpu_val = r["cpu"]
        mem_val = r["mem"]
        name_val = r["name"]
        click.echo(f"  {name_val:<40} "
                   f"CPU: {click.style(f'{cpu_val:5.1f}%', fg=cpu_color)}  "
                   f"MEM: {mem_val:6.0f} MB")
    click.echo()


@cli.command()
def nodes():
    """List all cluster nodes with SSH / TCP reachability."""
    ns = load_nodes()
    click.echo(f"\n{'NAME':<28} {'HOST':<18} {'ROLE':<12} {'STATUS'}")
    click.echo("─" * 70)
    for n in ns:
        host = n.get("host", "localhost")
        role = n.get("role", "?")
        name = n.get("name", host)
        up   = tcp_up(host) or host == "localhost"
        state = click.style("UP  ", fg="green") if up else click.style("DOWN", fg="red")
        click.echo(f"{name:<28} {host:<18} {role:<12} {state}")
    click.echo()


@cli.command()
def workflows():
    """Show active Temporal workflows."""
    async def _run():
        try:
            from temporalio.client import Client, WorkflowExecutionStatus
            client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=3.0)
            click.echo(f"\n{'ID':<44} {'STATUS':<12} {'TYPE'}")
            click.echo("─" * 80)
            found = False
            async for wf in client.list_workflows("ExecutionStatus='Running'"):
                click.echo(
                    f"{wf.id:<44} "
                    f"{click.style('RUNNING', fg='green'):<12} "
                    f"{wf.workflow_type}"
                )
                found = True
            if not found:
                click.echo("  No running workflows.")
        except Exception as e:
            click.echo(click.style(f"  Temporal unreachable: {e}", fg="yellow"))
        click.echo()

    asyncio.run(_run())


@cli.command()
def containers():
    """Show local Docker container stats (CPU / memory)."""
    rows = docker_stats()
    if not rows:
        click.echo("No containers found or Docker not accessible.")
        return
    click.echo(f"\n{'CONTAINER':<42} {'STATUS':<10} {'CPU %':>7} {'MEM MB':>8}")
    click.echo("─" * 72)
    for r in rows:
        cpu = r["cpu"]
        col  = "green" if cpu < 50 else "yellow" if cpu < 80 else "red"
        mem  = r["mem"]
        name = r["name"]
        st   = r["status"]
        click.echo(
            f"{name:<42} {st:<10} "
            f"{click.style(f'{cpu:7.1f}', fg=col)} "
            f"{mem:8.0f}"
        )
    click.echo()


@cli.command()
@click.option("--follow", "-f", is_flag=True, help="Follow live events from Redis.")
def logs(follow):
    """Tail the live event stream from the Observability Collector (via Redis)."""
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        if follow:
            click.echo(f"Subscribing to Redis obs:events on {REDIS_URL} — Ctrl+C to stop\n")
            p = r.pubsub()
            p.subscribe("obs:events")
            for msg in p.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        ts = data.get("ts", "")[:19].replace("T", " ")
                        nodes_down = [n["name"] for n in data.get("nodes", []) if not n.get("up")]
                        wf_active  = data.get("temporal", {}).get("active", "?")
                        containers_n = len(data.get("containers", []))
                        alert = ("  ⚠ DOWN: " + ", ".join(nodes_down)) if nodes_down else ""
                        click.echo(
                            f"{click.style(ts, fg='cyan')}  "
                            f"workflows={click.style(str(wf_active), fg='green')}  "
                            f"containers={containers_n}"
                            f"{click.style(alert, fg='red')}"
                        )
                    except Exception:
                        pass
        else:
            # One-shot: print last snapshot from collector API
            click.echo("No --follow flag. Use `logs --follow` for live stream.\n")
            status.callback()
    except ImportError:
        click.echo("redis package not installed. pip install redis")
    except Exception as e:
        click.echo(f"Error: {e}")


@cli.command()
def watch():
    """Launch the live Textual TUI dashboard."""
    try:
        from src.observability.cli.dashboard import ObsDashboard
        ObsDashboard().run()
    except ImportError as e:
        click.echo(f"Textual not installed: {e}\npip install textual")


if __name__ == "__main__":
    cli()
