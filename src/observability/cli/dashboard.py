"""
Textual TUI Dashboard — live 6-panel cluster monitor.
Launch with: PYTHONPATH=. python -m src.observability.cli watch
"""

import asyncio
import json
import os
import socket
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, Log, Static

REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6380")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
NODES_FILE    = os.path.join(os.path.dirname(__file__), "../../../config/cluster_nodes.yaml")
POLL_SEC      = int(os.getenv("POLL_INTERVAL", "10"))


def tcp_up(host, port=22, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return host == "localhost"


def load_nodes():
    try:
        import yaml
        with open(NODES_FILE) as f:
            return yaml.safe_load(f).get("nodes", [])
    except Exception:
        return [{"name": "local", "host": "localhost", "role": "cnc"}]


def docker_stats():
    try:
        import docker
        rows = []
        for ct in docker.from_env().containers.list():
            try:
                raw  = ct.stats(stream=False)
                cd   = raw["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       raw["precpu_stats"]["cpu_usage"]["total_usage"]
                sd   = raw["cpu_stats"]["system_cpu_usage"] - \
                       raw["precpu_stats"]["system_cpu_usage"]
                nc   = raw["cpu_stats"].get("online_cpus", 1)
                cpu  = (cd / sd) * nc * 100 if sd > 0 else 0
                mem  = raw["memory_stats"].get("usage", 0) / 1024 / 1024
                rows.append({"name": ct.name, "cpu": cpu, "mem": mem,
                             "status": ct.status})
            except Exception:
                pass
        return rows
    except Exception:
        return []


async def temporal_active():
    try:
        from temporalio.client import Client
        client = await asyncio.wait_for(Client.connect(TEMPORAL_HOST), timeout=3.0)
        n = 0
        async for _ in client.list_workflows("ExecutionStatus='Running'"):
            n += 1
        return n
    except Exception:
        return None


# ── Widgets ──────────────────────────────────────────────────────────────────

class Panel(Static):
    DEFAULT_CSS = """
    Panel {
        border: round $accent;
        padding: 0 1;
        height: 100%;
    }
    """


class NodePanel(Panel):
    nodes_data: reactive[list] = reactive([])

    def render(self):
        lines = ["[bold cyan]🌐 NODES[/]\n"]
        for n in self.nodes_data:
            up  = n.get("up", False)
            dot = "[green]●[/]" if up else "[red]○[/]"
            st  = "[green]UP[/]  " if up else "[red]DOWN[/]"
            lines.append(f" {dot} {n['name']:<22} {st} [{n['role']}]")
        return "\n".join(lines) if len(lines) > 1 else "[dim]Loading…[/]"


class WorkflowPanel(Panel):
    count: reactive = reactive(None)

    def render(self):
        if self.count is None:
            return "[bold cyan]⚙️  WORKFLOWS[/]\n\n [yellow]Temporal unreachable[/]"
        return (
            f"[bold cyan]⚙️  WORKFLOWS[/]\n\n"
            f" Active: [bold green]{self.count}[/]\n"
            f" Queue:  [dim]ai-orchestration-queue[/]"
        )


class ContainerPanel(Panel):
    data: reactive[list] = reactive([])

    def render(self):
        lines = ["[bold cyan]🐳 CONTAINERS[/]\n"]
        if not self.data:
            return "\n".join(lines) + "\n [dim]No containers[/]"
        lines.append(f" {'NAME':<34} {'CPU%':>6} {'MEM MB':>7}")
        lines.append(" " + "─" * 50)
        for r in self.data[:8]:
            cpu  = r["cpu"]
            col  = "green" if cpu < 50 else "yellow" if cpu < 80 else "red"
            name = r["name"][:33]
            lines.append(f" {name:<34} [{col}]{cpu:6.1f}[/] {r['mem']:7.0f}")
        return "\n".join(lines)


class ServicesPanel(Panel):
    def compose(self) -> ComposeResult:
        yield Label("[bold cyan]🔌 SERVICES[/]")

    def render(self):
        checks = [
            ("Temporal",   tcp_up("localhost", 7233)),
            ("Qdrant",     tcp_up("localhost", 6333)),
            ("Redis",      tcp_up("localhost", 6379)),
            ("Obs Redis",  tcp_up("localhost", 6380)),
        ]
        lines = ["[bold cyan]🔌 SERVICES[/]\n"]
        for name, up in checks:
            dot = "[green]●[/]" if up else "[red]○[/]"
            lines.append(f" {dot} {name}")
        return "\n".join(lines)


# ── Main TUI App ─────────────────────────────────────────────────────────────

class ObsDashboard(App):
    TITLE    = "AI Orchestrator — Cluster Monitor"
    CSS      = """
    Screen { background: #0a0d14; }
    Header { background: #111827; color: #3b82f6; }
    Footer { background: #111827; }
    .row   { height: 1fr; }
    NodePanel      { width: 1fr; }
    WorkflowPanel  { width: 1fr; }
    ServicesPanel  { width: 1fr; }
    ContainerPanel { width: 2fr; }
    #log-panel {
        height: 12;
        border: round $accent;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("q",   "quit",    "Quit"),
        ("r",   "refresh", "Refresh now"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(classes="row"):
                yield NodePanel(id="nodes")
                yield WorkflowPanel(id="workflows")
                yield ServicesPanel(id="services")
            with Horizontal(classes="row"):
                yield ContainerPanel(id="containers")
            yield Log(id="log-panel", highlight=True, markup=True)
        yield Footer()

    def on_mount(self):
        self.set_interval(POLL_SEC, self.refresh_data)
        self.call_after_refresh(self.refresh_data)

    async def refresh_data(self):
        nodes = load_nodes()
        enriched = []
        for n in nodes:
            host = n.get("host", "localhost")
            enriched.append({**n, "up": tcp_up(host) or host == "localhost"})

        node_panel = self.query_one("#nodes", NodePanel)
        node_panel.nodes_data = enriched

        wf_count = await temporal_active()
        self.query_one("#workflows", WorkflowPanel).count = wf_count

        stats = docker_stats()
        self.query_one("#containers", ContainerPanel).data = stats

        log = self.query_one("#log-panel", Log)
        up_n   = sum(1 for n in enriched if n["up"])
        down_n = len(enriched) - up_n
        ts     = datetime.now().strftime("%H:%M:%S")
        wf_s   = str(wf_count) if wf_count is not None else "?"
        log.write_line(
            f"[cyan]{ts}[/]  nodes {up_n}↑/{down_n}↓  "
            f"workflows={wf_s}  containers={len(stats)}"
        )

    def action_refresh(self):
        asyncio.create_task(self.refresh_data())


if __name__ == "__main__":
    ObsDashboard().run()
