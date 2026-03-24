#!/home/pi/Projects/ai-orchestration-project/venv/bin/python3
import os
import sys
import asyncio
import argparse
import logging
import time
from typing import Optional
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.config import load_settings
load_settings()

from src.genesis.analyzer.task_analyzer import TaskAnalyzer, AnalyzerResult
from src.genesis.cli import show_plan
from src.genesis.iac.pulumi_wrapper import provision_worker, destroy_worker
from src.genesis.orchestrator.scheduler import TaskScheduler
from src.genesis.utils.system_monitor import SystemMonitor

# Plugin system imports
try:
    from src.plugins.loader import load_tools as load_plugin_tools
    from src.plugins.registry import registry
    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False
    registry = None

monitor = SystemMonitor(threshold_percent=99.0)


async def start_listeners(scheduler: TaskScheduler):
    """Start all listener tools from the plugin registry."""
    if not PLUGINS_AVAILABLE or not registry:
        return
    
    listeners = registry.get_listeners()
    if not listeners:
        return
    
    logger_main = logging.getLogger("CNC")
    for tool in listeners:
        try:
            await tool.start_listener(scheduler.submit_task)
            logger_main.info(f"Started listener: {tool.name}")
        except Exception as e:
            logger_main.warning(f"Failed to start listener {tool.name}: {e}")


def preprocess_argv():
    """If the first positional arg isn't a known subcommand, inject 'submit'."""
    subcommands = {"submit", "status", "list"}
    # Find first positional arg (skip flags like --memory)
    for i, arg in enumerate(sys.argv[1:], start=1):
        if arg.startswith("-"):
            continue
        if arg not in subcommands:
            sys.argv.insert(i, "submit")
        return
    # No positional args found — don't inject anything (let argparse handle --memory etc.)


async def execute_task_async(result: AnalyzerResult, statement: str, wait: bool = False, scheduler: Optional[TaskScheduler] = None):
    """Submit a task. If wait=False (default), returns immediately after submission."""
    # 0. Proactive Memory Check
    if monitor.is_crash_imminent():
        print("\n⚠️  [CRITICAL] System memory usage is extremely high (>90%).")
        freed = monitor.free_memory([scheduler] if scheduler else [])
        print(f"🧹 Attempted to free memory (cleared {freed} cache entries).")
        monitor.save_state({"task_statement": statement, "plan": result.model_dump()})
        print("💾 State saved to data/last_state.json. Exiting for safety...")
        sys.exit(137)  # Standard OOM exit code

    # 1. Initial Connectivity Check (Proactive)
    if not scheduler:
        scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")

    print("\n🔍 [CHECK] Initial connectivity probe to core services...")
    conn_status = await scheduler.check_connectivity()
    for service, status in conn_status.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {service.capitalize()}: {'Reachable' if status else 'Offline'}")

    # 2. Provision Infrastructure via Pulumi
    stack_name = "prod-task-worker"
    project_name = "ai-orchestration"

    outputs = await provision_worker(stack_name, project_name, result.infrastructure_id, {})

    queue_url = outputs["queue_url"].value
    table_name = outputs["table_name"].value

    # 3. Schedule Task
    scheduler = TaskScheduler(queue_url, table_name)

    # Final Verification
    if not all(conn_status.values()):
        print("\n🔍 [CHECK] Verifying connectivity after provisioning...")
        conn_status = await scheduler.check_connectivity()
        if all(conn_status.values()):
            print("  ✅ All core services are now ONLINE.")
        else:
            for service, status in conn_status.items():
                if not status:
                    print(f"  ❌ {service.capitalize()} is still OFFLINE.")

    print(f"\n🚀 [ORCHESTRATOR] Delegating task to {result.infrastructure_id}...")
    print(f"📥 Pushing task to queue: \"{statement}\"")
    task_id = await scheduler.submit_task(statement, result.model_dump())

    print(f"\n✅ Task submitted: {task_id}")

    if wait:
        # Legacy blocking mode
        print(f"⏳ Waiting for completion (--wait mode)...")
        final_status = await scheduler.wait_for_completion(task_id)
        print(f"\n🏁 Task {task_id} finished with status: {final_status}")
    else:
        # Fire-and-forget (new default)
        print(f"\n📋 Check progress:  ./main.py status {task_id}")
        print(f"📋 Live watch:      ./main.py status {task_id} --watch")
        print(f"📋 List all tasks:  ./main.py list")
        if scheduler.notifier and scheduler.notifier.enabled:
            print(f"📋 Telegram notifications are active — you'll be pinged on completion.")

    return task_id


async def handle_submit(args):
    """Handle the 'submit' subcommand."""
    analyzer = TaskAnalyzer(config_path=args.config)

    print(f"🔍 Analyzing statement: \"{args.statement}\"")

    # Pre-flight Memory Check
    if monitor.is_crash_imminent():
        print("⚠️  Warning: High memory usage detected before analysis. Clearing caches...")
        monitor.free_memory([analyzer])

    # 1. Parse natural language to structured requirements (Async)
    task_req = await analyzer.parse_statement(args.statement)

    # 2. Analyze requirements for optimal infra and model
    result = analyzer.analyze(task_req)

    # Override infrastructure if using existing
    if args.use_existing:
        result.infrastructure_id = "existing_server"
        result.infra_details = {"provider": "existing_infra", "type": "container", "startup_time_sec": 1}
        result.reason = "User requested to use existing infrastructure."

    # Determine the statement to send — all tasks use the agentic pipeline now
    import json as _json
    agent_payload = {
        "task_type": "agent",
        "description": args.statement,
        "repo_url": getattr(args, "repo_url", ""),
        "max_tool_calls": getattr(args, "max_tool_calls", 50),
        "max_cost_usd": getattr(args, "max_cost", 0.50),
        "specialization": result.specialization
    }
    if getattr(args, "push_branch", ""):
        agent_payload["push_branch"] = args.push_branch
    effective_statement = _json.dumps(agent_payload)

    if args.agent:
        print(f"🤖 [AGENT MODE] Task will run as autonomous agent")

    if args.plan or not args.yolo:
        # INTERACTIVE MODE (Default or if --plan is specified)
        show_plan(result)
        if not args.yolo:
            print("\n[PROMPT] Running in safe mode. Use --yolo to bypass this check.")

        while True:
            choice = input("\nOptions: [e]xecute, [r]ecalculate (manual params), [m]emory, [q]uit: ").lower().strip()

            if choice == 'e':
                await execute_task_async(result, effective_statement, wait=args.wait)
                break
            elif choice == 'r':
                from src.genesis.cli import build_task
                manual_task = build_task()
                manual_result = analyzer.analyze(manual_task)
                show_plan(manual_result)
                if input("Execute this new plan? (y/n): ").lower() == 'y':
                    await execute_task_async(manual_result, effective_statement, wait=args.wait)
                break
            elif choice == 'm' or choice == '/memory':
                stats = monitor.get_memory_stats()
                print(f"🧠 Memory Usage: {stats['percent']}% ({stats['used_gb']}GB/{stats['total_gb']}GB used)")
            elif choice == 'q':
                print("Aborted.")
                break
            else:
                print("Invalid choice.")
    else:
        # AUTOMATIC MODE (Only if --yolo is specified and --plan is NOT specified)
        print("🚀 [YOLO] Auto-executing task...")
        await execute_task_async(result, effective_statement, wait=args.wait)


async def handle_status(args):
    """Handle the 'status' subcommand."""
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")

    if args.watch:
        # Live-watch mode: poll until done, with Telegram notifications
        print(f"⏳ Watching task {args.task_id} until completion...")
        final_status = await scheduler.wait_for_completion(args.task_id)
        print(f"\n🏁 Task {args.task_id} finished with status: {final_status}")
    else:
        # One-shot status query
        detail = await scheduler.get_task_detail(args.task_id)
        print(f"\n📋 Task Status")
        print(f"   ID:          {detail['task_id']}")
        print(f"   Description: {detail['description']}")
        print(f"   Status:      {detail['status']}")
        if detail.get('start_time'):
            print(f"   Started:     {detail['start_time']}")
        if detail.get('close_time'):
            print(f"   Completed:   {detail['close_time']}")
        if detail.get('result'):
            result = detail['result']
            if isinstance(result, dict):
                cost = result.get('total_cost_usd', 0.0)
                if cost:
                    print(f"   Cost:        ${cost:.6f} USD")
                if result.get('mode') == 'agent':
                    # Agent mode result
                    tool_calls = result.get('tool_call_count', 0)
                    duration = result.get('duration_seconds', 0)
                    summary = result.get('summary', '')
                    print(f"   Tool Calls:  {tool_calls}")
                    print(f"   Duration:    {duration:.1f}s")
                    if summary:
                        print(f"\n   📋 Summary:\n   {summary[:2000]}")
                    progress = result.get('progress_log', [])
                    if progress:
                        print(f"\n   📈 Progress Log:")
                        for entry in progress[-10:]:
                            print(f"      - {entry}")
                else:
                    # Legacy mode result
                    assessment = result.get('assessment', '')
                    recommendations = result.get('recommendations', '')
                    if assessment:
                        print(f"\n   🧠 Assessment:\n   {assessment[:2000]}")
                    if recommendations:
                        print(f"\n   💡 Recommendations:\n   {recommendations[:2000]}")
            else:
                print(f"   Result:      {result}")


async def handle_list(args):
    """Handle the 'list' subcommand."""
    scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    tasks = scheduler.get_recent_tasks(limit=20)

    if not tasks:
        print("\n📋 No tasks found.")
        return

    print(f"\n📋 Recent Tasks ({len(tasks)})")
    print(f"{'ID':<38} {'Status':<16} {'Submitted':<20} Description")
    print("-" * 100)
    for t in tasks:
        submitted = time.strftime("%Y-%m-%d %H:%M", time.localtime(t['submitted_at'])) if t['submitted_at'] else "?"
        desc = t['description'][:40] + "..." if len(t['description']) > 40 else t['description']
        print(f"{t['task_id']:<38} {t['status']:<16} {submitted:<20} {desc}")


async def main_async():
    # Startup notification kept local — Telegram channel was getting spammed on every CLI invocation
    logger_main = logging.getLogger("CNC")
    logger_main.info("Genesis Node CLI initialized.")

    # Load plugin tools for genesis node
    if PLUGINS_AVAILABLE:
        try:
            await load_plugin_tools("config/bootstrap.yaml", node="genesis")
            logger_main.info(f"Loaded {len(registry._tools)} genesis tools from plugin registry")
            # Start listeners in background
            scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
            await start_listeners(scheduler)
        except Exception as e:
            logger_main.warning(f"Could not load genesis plugin tools: {e}")

    # Preprocess argv so bare task strings route to 'submit'
    preprocess_argv()

    parser = argparse.ArgumentParser(description="AI Task Orchestrator - Genesis/CNC Node")
    parser.add_argument("--memory", action="store_true", help="Show current system memory usage stats and exit")

    subparsers = parser.add_subparsers(dest="command")

    # Submit subcommand
    submit_parser = subparsers.add_parser("submit", help="Submit a new task (default)")
    submit_parser.add_argument("statement", help="Natural language description of the task")
    submit_parser.add_argument("--plan", action="store_true", help="Review the execution plan before proceeding")
    submit_parser.add_argument("--yolo", action="store_true", help="Bypass plan review and auto-execute")
    submit_parser.add_argument("--use-existing", action="store_true", help="Use existing infrastructure")
    submit_parser.add_argument("--config", default="config/profiles.yaml", help="Path to profiles configuration")
    submit_parser.add_argument("--wait", action="store_true", help="Block until task completes (legacy behavior)")
    submit_parser.add_argument("--agent", action="store_true", help="Run task in autonomous agent mode with tools")
    submit_parser.add_argument("--repo-url", default=os.environ.get("AGENT_DEFAULT_REPO", "ssh://git@github.com/rinehardramos/workspaces.git"),
                               help="Git repo URL for agent to work with (defaults to AGENT_DEFAULT_REPO)")
    submit_parser.add_argument("--max-tool-calls", type=int, default=50, help="Max tool calls for agent mode")
    submit_parser.add_argument("--max-cost", type=float, default=0.50, help="Max cost in USD for agent mode")
    submit_parser.add_argument("--push-branch", default="", help="Hint branch name for agent to push results to (e.g. agent/my-feature)")

    # Status subcommand
    status_parser = subparsers.add_parser("status", help="Check status of a task")
    status_parser.add_argument("task_id", help="Task ID to check")
    status_parser.add_argument("--watch", action="store_true", help="Live-watch until task completes")

    # List subcommand
    subparsers.add_parser("list", help="List recent tasks")

    args = parser.parse_args()

    if args.memory:
        stats = monitor.get_memory_stats()
        print(f"\n🧠 [SYSTEM MEMORY STATUS]")
        print(f"   Usage:      {stats['percent']}%")
        print(f"   Used:       {stats['used_gb']} GB")
        print(f"   Available:  {stats['available_gb']} GB")
        print(f"   Total:      {stats['total_gb']} GB")
        sys.exit(0)

    if args.command == "submit":
        await handle_submit(args)
    elif args.command == "status":
        await handle_status(args)
    elif args.command == "list":
        await handle_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
