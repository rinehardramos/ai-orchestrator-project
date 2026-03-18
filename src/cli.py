import os
import sys
import yaml
from pydantic import ValidationError

# Ensure we're in the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.analyzer.agent import AnalyzerAgent, TaskRequirement, AnalyzerResult

def get_input_with_default(prompt, default):
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default

def build_task() -> TaskRequirement:
    print("\n--- Enter Task Requirements ---")
    duration = int(get_input_with_default("Estimated duration (seconds)", "60"))
    memory = int(get_input_with_default("Memory (MB)", "512"))
    complexity = get_input_with_default("Reasoning Complexity (low, medium, high, extreme)", "low")
    context = int(get_input_with_default("Context Length (tokens)", "1000"))
    suspension = get_input_with_default("Requires State Suspension? (y/n)", "n").lower() == 'y'
    concurrency = get_input_with_default("Requires High Concurrency? (y/n)", "n").lower() == 'y'
    
    return TaskRequirement(
        estimated_duration_seconds=duration,
        memory_mb=memory,
        reasoning_complexity=complexity,
        context_length=context,
        requires_state_suspension=suspension,
        requires_concurrency=concurrency
    )

def show_plan(result: AnalyzerResult):
    print("\n" + "="*40)
    print("      PROPOSED EXECUTION PLAN      ")
    print("="*40)
    print(f"Infrastructure: {result.infrastructure_id}")
    print(f"   Provider:    {result.infra_details['provider']}")
    print(f"   Type:        {result.infra_details['type']}")
    print(f"   Startup:     ~{result.infra_details['startup_time_sec']}s")
    print(f"LLM Model:      {result.llm_model_id}")
    print(f"   Provider:    {result.model_details['provider']}")
    print(f"   Reasoning:   {result.model_details['reasoning_capability']}")
    print("-" * 40)
    print(f"Estimated Cost: ${result.estimated_cost:.6f}")
    print(f"Reason:         {result.reason}")
    print("=" * 40)

def main():
    try:
        from src.orchestrator.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        if notifier.enabled:
            notifier.send_message("🤖 *Gemini CLI Initialized*\nGenesis Node is now online and ready to accept tasks.")
    except Exception as e:
        pass

    agent = AnalyzerAgent()
    task = build_task()
    
    while True:
        try:
            result = agent.analyze(task)
            show_plan(result)
            
            choice = input("\nOptions: [e]xecute, [r]ecalculate (change params), [q]uit: ").lower().strip()
            
            if choice == 'e':
                print(f"\n🚀 Executing on {result.infrastructure_id} with {result.llm_model_id}...")
                # Here we would call the iac wrapper
                print("Execution dummy complete. Done.")
                break
            elif choice == 'r':
                task = build_task()
                continue
            elif choice == 'q':
                print("Quitting plan.")
                break
            else:
                print("Invalid choice.")
                
        except (ValueError, ValidationError) as e:
            print(f"\n❌ Error in task/analysis: {e}")
            choice = input("Would you like to [r]ecalculate or [q]uit? ").lower().strip()
            if choice == 'r':
                task = build_task()
                continue
            else:
                break

if __name__ == "__main__":
    main()
