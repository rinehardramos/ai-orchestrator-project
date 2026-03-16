# AI Orchestration Project: Intelligent Task Worker

An autonomous orchestrator designed to run on low-power hardware (like a Raspberry Pi) that dynamically provisions ephemeral, cost-optimized cloud infrastructure and LLM models to execute tasks.

## 🚀 Key Features

- **Infrastructure & Model Analyzer Agent**: Uses Gemini 1.5 to parse natural language task descriptions and determine the most economical and efficient setup.
- **2026-Era Profiles**: Pre-configured with the latest serverless and frontier models (Gemini 3.1, GPT-5.4, Claude 4.6).
- **Ephemeral Infrastructure (IaC)**: Programmatically provisions and destroys resources using the Pulumi Automation API to ensure zero idle costs.
- **RAG-Ready**: Designed to connect to serverless vector databases for task memory and long-term state.
- **Dual Modes**: 
  - **Automatic**: High-speed, one-step "Analyze & Execute" flow.
  - **Plan (Dry Run)**: Interactive mode to review reasoning, costs, and adjust parameters before deployment.

## 🛠️ Prerequisites

- **Python 3.13+**
- **Pulumi CLI**: Installed and configured with your cloud provider (AWS/GCP).
- **Cloud CLIs**: `aws` and `gh` (GitHub) CLI installed and authenticated.
- **API Keys**: 
  - `GOOGLE_API_KEY`: Required for the Analyzer Agent's natural language parsing.

## 🔐 Authentication & Secrets

The orchestrator uses standard environment variables and system-level authentication. **Never** commit your `.env` file or cloud credentials to source control.

### **1. LLM API Keys**
Copy the template and add your keys:
```bash
cp .env.template .env
# Edit .env with your Google, OpenAI, or Anthropic keys
```

### **2. Cloud Provider Auth**
The orchestrator uses **Pulumi** and the official CLIs for cloud provisioning.

- **AWS**: Run `aws configure` to set up credentials in `~/.aws/credentials`.
- **GCP**: Run `gcloud auth application-default login` to set up Application Default Credentials.

## 📦 Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd ai-orchestration-project
   ```

2. **Setup Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Profiles**:
   Review and adjust `config/profiles.yaml` to match your budget and preferred cloud providers.

## 📖 Usage

### **1. Automatic Execution**
Provide a natural language statement. The agent will analyze requirements (RAM, duration, reasoning complexity) and execute immediately.
```bash
export GOOGLE_API_KEY="your-key"
python3 main.py "summarize this 500-page legal document and check for compliance"
```

### **2. Plan Mode (Dry Run)**
Use the `--plan` flag to see the "Dry Run" report. You can review the choice and manually override parameters if the automated choice isn't what you wanted.
```bash
python3 main.py --plan "process 50GB of raw logs and detect anomalies"
```

## 🏗️ Project Structure

- `main.py`: Entry point for the orchestrator.
- `src/analyzer/`: Core logic for task parsing and infrastructure selection.
- `src/iac/`: Pulumi Automation API wrappers for cloud provisioning.
- `src/cli.py`: Interactive CLI components for Plan mode.
- `config/`: YAML-based profiles for models and infrastructure.
- `tests/`: Unit tests for the analyzer logic.

## ⚙️ Configuration

The `config/profiles.yaml` file defines the limits and costs for both infrastructure and models. The agent uses these values to calculate the most cost-effective path.

```yaml
infrastructure:
  - id: "aws_lambda_durable"
    cost_per_minute: 0.000016
    max_memory_mb: 10240
    best_for: "stateful_burst"
...
models:
  - id: "gemini-3.1-flash-lite"
    cost_per_1k_tokens: 0.00001
    reasoning_capability: "low"
```

## 🧪 Running Tests

```bash
pytest tests/test_agent.py
```

## 🧩 Installing as a Gemini CLI Skill

You can integrate the Analyzer Agent directly into your Gemini CLI to get architectural and cost advice in any session.

### **1. Install the Skill**
The packaged skill is located in `analyzer-agent-skill/dist/`.

**Workspace Scope (Current Project only):**
```bash
gemini skills install analyzer-agent-skill/dist/analyzer-agent.skill --scope workspace
```

**User Scope (Global):**
```bash
gemini skills install analyzer-agent-skill/dist/analyzer-agent.skill --scope user
```

### **2. Activate the Skill**
In your interactive Gemini CLI session, run the reload command:
```bash
/skills reload
```

### **3. Example Usage**
Once installed, you can ask Gemini CLI to use the agent for planning:
> "Use the analyzer-agent to plan a task for processing 10GB of logs."

