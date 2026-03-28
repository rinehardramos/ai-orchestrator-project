---
name: analyzer-agent
description: AI Task Orchestrator and Infrastructure Analyzer. Use when you need to determine the most cost-effective and efficient cloud infrastructure (AWS/GCP/Local) and LLM model (Gemini/GPT/Claude) for a specific task based on natural language descriptions.
---

# Analyzer Agent Skill

This skill allows Gemini CLI to leverage the local "Analyzer Agent" to optimize task execution across various cloud providers and AI models.

## Core Workflow

The agent uses **Gemini 1.5** to parse task statements and maps them to pre-defined infrastructure and model profiles in `config/profiles.yaml`.

### 1. Analyze & Plan (Dry Run)
Use this when you want to see the recommended setup and estimated cost before committing to a deployment.

**Command:**
```bash
python3 main.py --plan "[Task Description]"
```

**What to look for in the output:**
- **Infrastructure**: AWS Lambda, EC2 Spot, GCP Cloud Run, or Local Pi.
- **LLM Model**: High-reasoning (GPT-5.4/Claude 4.6) vs. High-speed (Gemini 3.1 Flash).
- **Estimated Cost**: The total projected cost for the task.

### 2. Automatic Execution
Use this for one-step analysis and deployment when you are confident in the defaults.

**Command:**
```bash
python3 main.py "[Task Description]"
```

## Integration with Gemini CLI

When acting as an architect, use this agent to:
1. **Validate Assumptions**: Run a `--plan` to see if a task is "heavy" enough to justify a dedicated EC2 instance.
2. **Cost Analysis**: Compare different task descriptions to see how the agent adjusts its recommendations.
3. **Provisioning**: The agent uses the **Pulumi Automation API** to programmatically spin up the chosen environment.

## Resources

- **Profiles**: `config/profiles.yaml` (Edit this to add new models or adjust provider costs).
- **Orchestrator**: `main.py` (The main entry point for the agent).
- **Logic**: `src/analyzer/agent.py` (The scoring and selection algorithm).
