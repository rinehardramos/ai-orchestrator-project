import os
import sys
import argparse
import asyncio
from typing import Optional
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.analyzer.agent import AnalyzerAgent, TaskRequirement, AnalyzerResult
from src.cli import show_plan
from src.iac.pulumi_wrapper import provision_worker, destroy_worker
from src.orchestrator.scheduler import TaskScheduler

async def execute_task(result: AnalyzerResult, statement: str):
    print(f"\n🚀 [ORCHESTRATOR] Provisioning {result.infrastructure_id}...")
    
    # 1. Provision Infrastructure via Pulumi
    # We use a static stack name for simplicity in this example, or dynamic based on task
    stack_name = "prod-task-worker"
    project_name = "ai-orchestration"
    
    outputs = await provision_worker(stack_name, project_name, result.infrastructure_id, {})
    
    queue_url = outputs["queue_url"].value
    table_name = outputs["table_name"].value

    # 2. Schedule Task
    scheduler = TaskScheduler(queue_url, table_name)
    print(f"📥 Pushing task to queue: \"{statement}\"")
    task_id = scheduler.submit_task(statement, {
        "model": result.llm_model_id,
        "infra": result.infrastructure_id
    })
    
    print(f"✅ Task registered: {task_id}")
    
    # 3. Monitor Status
    final_status = scheduler.wait_for_completion(task_id)
    print(f"\n🏁 Task {task_id} finished with status: {final_status}")

    # 4. Optional: Cleanup (Destroy worker if no more tasks)
    # await destroy_worker(stack_name, project_name, result.infrastructure_id)

async def main():
    parser = argparse.ArgumentParser(description="AI Task Orchestrator - Analyzer Agent")
    parser.add_argument("statement", nargs="?", help="Natural language description of the task")
    parser.add_argument("--plan", action="store_true", help="Review the execution plan before proceeding")
    parser.add_argument("--config", default="config/profiles.yaml", help="Path to profiles configuration")
    
    args = parser.parse_args()
    
    if not args.statement:
        print("Error: No task statement provided.")
        parser.print_help()
        return

    agent = AnalyzerAgent(config_path=args.config)
    
    print(f"🔍 Analyzing statement: \"{args.statement}\"")
    try:
        # 1. Parse natural language to structured requirements
        task_req = agent.parse_statement(args.statement)
        
        # 2. Analyze requirements for optimal infra and model
        result = agent.analyze(task_req)
        
        if args.plan:
            # INTERACTIVE MODE
            show_plan(result)
            choice = input("\nOptions: [e]xecute, [r]ecalculate (manual params), [q]uit: ").lower().strip()
            
            if choice == 'e':
                await execute_task(result, args.statement)
            elif choice == 'r':
                from src.cli import build_task
                manual_task = build_task()
                manual_result = agent.analyze(manual_task)
                show_plan(manual_result)
                if input("Execute this new plan? (y/n): ").lower() == 'y':
                    await execute_task(manual_result, args.statement)
            else:
                print("Aborted.")
        else:
            # AUTOMATIC MODE
            await execute_task(result, args.statement)
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
