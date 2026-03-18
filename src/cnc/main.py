#!/home/pi/Projects/ai-orchestration-project/venv/bin/python3
import os
import sys
import asyncio
import argparse
from typing import Optional
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.cnc.analyzer.agent import AnalyzerAgent, TaskRequirement, AnalyzerResult
from src.cnc.cli import show_plan
from src.cnc.iac.pulumi_wrapper import provision_worker, destroy_worker
from src.cnc.orchestrator.scheduler import TaskScheduler
from src.cnc.utils.system_monitor import SystemMonitor

monitor = SystemMonitor(threshold_percent=90.0)

async def execute_task_async(result: AnalyzerResult, statement: str, scheduler: Optional[TaskScheduler] = None):
    # 0. Proactive Memory Check
    if monitor.is_crash_imminent():
        print("\n⚠️  [CRITICAL] System memory usage is extremely high (>90%).")
        freed = monitor.free_memory([scheduler] if scheduler else [])
        print(f"🧹 Attempted to free memory (cleared {freed} cache entries).")
        monitor.save_state({"task_statement": statement, "plan": result.dict()})
        print("💾 State saved to data/last_state.json. Exiting for safety...")
        sys.exit(137) # Standard OOM exit code

    # 1. Initial Connectivity Check (Proactive)
    if not scheduler:
        scheduler = TaskScheduler("dummy-temporal-queue", "dummy-qdrant-db")
    
    print("\n🔍 [CHECK] Initial connectivity probe to core services...")
    conn_status = await scheduler.check_connectivity()
    for service, status in conn_status.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {service.capitalize()}: {'Reachable' if status else 'Offline'}")

    # 1. Provision Infrastructure via Pulumi
    stack_name = "prod-task-worker"
    project_name = "ai-orchestration"
    
    # If already reachable, we might skip heavy provisioning logic if the user uses --use-existing
    outputs = await provision_worker(stack_name, project_name, result.infrastructure_id, {})
    
    queue_url = outputs["queue_url"].value
    table_name = outputs["table_name"].value

    # 2. Schedule Task
    scheduler = TaskScheduler(queue_url, table_name)
    
    # Final Verification
    if not all(conn_status.values()):
        print("\n🔍 [CHECK] Verifying connectivity after provisioning...")
        conn_status = await scheduler.check_connectivity()
        if all(conn_status.values()):
            print("  ✅ All core services are now ONLINE.")
        else:
            for service, status in conn_status.items():
                if not status: print(f"  ❌ {service.capitalize()} is still OFFLINE.")

    print(f"\n🚀 [ORCHESTRATOR] Delegating task to {result.infrastructure_id}...")
    print(f"📥 Pushing task to queue: \"{statement}\"")
    task_id = await scheduler.submit_task(statement, result.dict())
    
    print(f"✅ Task registered: {task_id}")
    
    # 3. Monitor Status
    final_status = await scheduler.wait_for_completion(task_id)
    print(f"\n🏁 Task {task_id} finished with status: {final_status}")

async def main_async():
    try:
        from src.cnc.orchestrator.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        if notifier.enabled:
            notifier.send_message("🤖 *Gemini CLI Initialized*\nGenesis Node is now online and ready to accept tasks.")
    except Exception as e:
        print(f"Failed to send initialization notification: {e}")

    parser = argparse.ArgumentParser(description="AI Task Orchestrator - Genesis/CNC Node")
    parser.add_argument("statement", nargs="?", help="Natural language description of the task")
    parser.add_argument("--plan", action="store_true", help="Review the execution plan before proceeding")
    parser.add_argument("--use-existing", action="store_true", help="Use existing infrastructure instead of provisioning dynamically")
    parser.add_argument("--config", default="config/profiles.yaml", help="Path to profiles configuration")
    parser.add_argument("--memory", action="store_true", help="Show current system memory usage stats and exit")
    
    args = parser.parse_args()
    
    if args.memory:
        stats = monitor.get_memory_stats()
        print(f"\n🧠 [SYSTEM MEMORY STATUS]")
        print(f"   Usage:      {stats['percent']}%")
        print(f"   Used:       {stats['used_gb']} GB")
        print(f"   Available:  {stats['available_gb']} GB")
        print(f"   Total:      {stats['total_gb']} GB")
        sys.exit(0)

    if not args.statement:
        print("❌ Error: Task statement is required unless using --memory.")
        parser.print_help()
        sys.exit(1)

    agent = AnalyzerAgent(config_path=args.config)
    
    print(f"🔍 Analyzing statement: \"{args.statement}\"")
    try:
        # Pre-flight Memory Check
        if monitor.is_crash_imminent():
            print("⚠️  Warning: High memory usage detected before analysis. Clearing caches...")
            monitor.free_memory([agent])

        # 1. Parse natural language to structured requirements (Async)
        task_req = await agent.parse_statement(args.statement)
        
        # 2. Analyze requirements for optimal infra and model
        result = agent.analyze(task_req)
        
        # Override infrastructure if using existing
        if args.use_existing:
            result.infrastructure_id = "existing_server"
            result.infra_details = {"provider": "existing_infra", "type": "container", "startup_time_sec": 1}
            result.reason = "User requested to use existing infrastructure."
        
        if args.plan:
            # INTERACTIVE MODE
            show_plan(result)
            while True:
                choice = input("\nOptions: [e]xecute, [r]ecalculate (manual params), [m]emory, [q]uit: ").lower().strip()
                
                if choice == 'e':
                    await execute_task_async(result, args.statement)
                    break
                elif choice == 'r':
                    from src.cnc.cli import build_task
                    manual_task = build_task()
                    manual_result = agent.analyze(manual_task)
                    show_plan(manual_result)
                    if input("Execute this new plan? (y/n): ").lower() == 'y':
                        await execute_task_async(manual_result, args.statement)
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
            # AUTOMATIC MODE
            await execute_task_async(result, args.statement)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main_async())
