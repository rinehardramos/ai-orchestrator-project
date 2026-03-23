# AI Orchestration Project: Genesis CNC & Intelligent Worker Nodes

An autonomous, multi-tier orchestrator designed to run as a **Genesis Node (L0 CNC)** on low-power hardware (like a Raspberry Pi 3) that delegates complex reasoning tasks to **Remote Worker Nodes** via Temporal and Pulumi.

## 🚀 Key Features

- **Genesis Node (Thin CNC)**: Optimized for Raspberry Pi 3 (1GB RAM). Handles intent parsing and delegation without local heavy lifting.
- **Durable Orchestration (Temporal)**: Uses Temporal.io to ensure task execution is resilient, retryable, and stateful across ephemeral workers.
- **Multi-Model Support via LiteLLM**: Unified proxy abstraction for Gemini, Claude, GPT-4, and other providers — swap models without touching worker code.
- **Infrastructure & Model Analyzer Agent**: Dynamically determines the most economical and efficient execution environment and model for each task.
- **Automated Remote Provisioning**: Dynamically syncs code and provisions Dockerized environments on remote servers (via SSH/Pulumi) or cloud (AWS/GCP).
- **Tiered Memory System**:
  - **L1 (Redis)**: Fast ephemeral cache.
  - **L2 (Qdrant)**: Persistent semantic vector memory — shared across all agents for cross-agent knowledge.
  - **L3 (S3/Local)**: Cold archival audit trails.
- **Agent Feedback Loop**: Workers embed resolved bugs and insights into Qdrant (L2). All agents query this shared knowledge base before execution, creating a continuous self-improvement cycle.
- **Real-time Notifications**: Telegram integration for task status updates (submitted, running, complete, failed, blocked).
- **Offline Resilience**: Local SQLite queue for tasks submitted when the Control Plane is unreachable — auto-flushed on reconnect.
- **Dual Modes**:
  - **Automatic**: High-speed, one-step "Analyze & Execute" flow.
  - **Plan (Dry Run)**: Interactive mode to review reasoning, costs, and connectivity status.

## 🛠️ Prerequisites

- **Python 3.13+**
- **Pulumi CLI**: Installed on the Genesis Node.
- **Docker & Docker Compose**: Installed on the Remote Worker Node.
- **Temporal Server**: Running on the Control Plane node (provisioned automatically by Genesis).
- **API Keys** (one or more, depending on the models you use):
  - `ANTHROPIC_API_KEY`: For Claude models (recommended).
  - `GOOGLE_API_KEY`: For Gemini models.
  - `OPENAI_API_KEY`: For GPT models.

## 🔐 Configuration

The project uses two primary configuration files:
- `config/profiles.yaml`: Defines available LLM models and infrastructure tiers (costs, limits).
- `config/settings.yaml`: Defines your local network topology (Remote host IP, SSH keys, Ports).

### **Example `config/settings.yaml`**
```yaml
remote_worker:
  host: "192.168.100.249"
  user: "your-user"
  ssh_key_path: "~/.ssh/id_ed25519"
  project_dir: "ai-orchestration-worker"

temporal:
  host: "192.168.100.249"
  port: 7233
```

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

3. **Configure Secrets**:
   ```bash
   cp .env.template .env
   # Add your API keys (at least one LLM provider is required)
   # ANTHROPIC_API_KEY=...
   # GOOGLE_API_KEY=...
   # OPENAI_API_KEY=...
   ```

## 📖 Usage

### **1. Execute Task**
Run the orchestrator from the Genesis Node (Pi):
```bash
./main.py "Run a security audit on the current codebase"
```
### **2. Plan & Provision**
Review the plan and check if the remote core services (Temporal, Qdrant) are reachable before committing:
```bash
./main.py --plan "Assess system performance"
```

### **3. Telegram Ingress Control (Headless Mode)**
The Genesis Node can be controlled remotely via Telegram. This is ideal for headless Raspberry Pi deployments.

- **Start Monitor**: 
  ```bash
  python3 src/genesis/orchestrator/telegram_monitor.py
  ```
- **Install Background Service**:
  Run the setup script and follow the prompts to install the `systemd` service:
  ```bash
  ./scripts/setup.sh
  ```
- **Commands**:
  - `/status`: Check if the Genesis node is online.
  - `/start`: Welcome message and instructions.
  - `<Any Text>`: Treat as a task statement for the AI to analyze and execute.
- **Monitoring Logs**:
  ```bash
  journalctl -u telegram-monitor -f
  ```

## 🔄 Development & Reloading

To apply changes made to the codebase, follow these steps based on the component modified:

### **1. Genesis Node Logic (Python)**
If you modify files in `src/genesis/` (like `orchestrator/` or `analyzer/`):
- No explicit reload is needed. Simply run `./main.py` or `python3 src/genesis/cli.py` again.

### **2. Remote Worker Node**
If you modify `src/execution/worker/worker.py` or the worker's environment:
- **Restart Worker**: Access the remote machine and restart the Docker container:
  ```bash
  docker compose restart worker
  ```
- **Update Infrastructure**: If you changed Pulumi logic or `jobs.yaml`, run `./main.py --plan` to trigger a re-provisioning cycle.

## 🏗️ Project Structure

The project is organized into three "planes" to clearly separate responsibilities:

- **Genesis Plane (`src/genesis/`)**: 
  - `main.py`: Entry point for the Genesis Genesis Node.
  - `analyzer/`: Intent parsing and infrastructure selection (via LiteLLM).
  - `iac/`: Pulumi SSH/Command orchestration for remote provisioning.
  - `orchestrator/`: Temporal client and task scheduler.
- **Control Plane (`src/control/`)**:
  - `catalog/`, `dispatcher/`, `model_selector/`, `scaler/`: Modular services for task lifecycle management.
  - `workflows/`: Temporal durable workflow definitions.
- **Execution Plane (`src/execution/`)**:
  - `worker/`: Logic for the remote execution environment.
- **Shared Plane (`src/shared/`)**:
  - `memory/`: Tiered L1/L2/L3 memory store clients.
  - `utils/`: Common helpers used across all planes.

## 🌐 Cluster Expansion: Adding Remote Workers

To add more machines to your AI Orchestration cluster as workers:

1. **Network Connectivity**:
   - Ensure the new machine can reach the **Control Plane (Central Node)** on ports:
     - `7233` (Temporal Server)
     - `6333` (Qdrant Vector DB)

2. **Setup on New Machine**:
   - Clone this repository.
   - Install dependencies: `pip install -r requirements.txt`.

3. **Configure Connection**:
   - Create or update the `.env` file with the Central Node's IP:
     ```env
     TEMPORAL_HOST_URL=192.168.x.x:7233
     QDRANT_URL=http://192.168.x.x:6333
     ```

4. **Launch Worker**:
   ```bash
   python src/execution/worker/worker.py
   ```
   The new worker will immediately start polling the `ai-orchestration-queue` and executing delegated tasks.

---
