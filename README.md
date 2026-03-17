# AI Orchestration Project: Genesis CNC & Intelligent Worker Nodes

An autonomous, multi-tier orchestrator designed to run as a **Genesis Node (L0 CNC)** on low-power hardware (like a Raspberry Pi 3) that delegates complex reasoning tasks to **Remote Worker Nodes** via Temporal and Pulumi.

## 🚀 Key Features

- **Genesis Node (Thin CNC)**: Optimized for Raspberry Pi 3 (1GB RAM). Handles intent parsing and delegation without local heavy lifting.
- **Durable Orchestration (Temporal)**: Uses Temporal.io to ensure task execution is resilient, retryable, and stateful across ephemeral workers.
- **Infrastructure & Model Analyzer Agent**: Uses Gemini 3 Flash to determine the most economical and efficient execution environment.
- **Automated Remote Provisioning**: Dynamically syncs code and provisions Dockerized environments on remote servers (via SSH/Pulumi) or cloud (AWS/GCP).
- **Tiered Memory System**:
  - **L1 (Redis)**: Fast ephemeral cache.
  - **L2 (Qdrant)**: Persistent semantic vector memory.
  - **L3 (S3/Local)**: Cold archival audit trails.
- **Dual Modes**: 
  - **Automatic**: High-speed, one-step "Analyze & Execute" flow.
  - **Plan (Dry Run)**: Interactive mode to review reasoning, costs, and connectivity status.

## 🛠️ Prerequisites

- **Python 3.13+**
- **Pulumi CLI**: Installed on the Genesis Node.
- **Docker & Docker Compose**: Installed on the Remote Worker Node.
- **Temporal Server**: Running on the worker node (provisioned automatically by Genesis).
- **API Keys**: 
  - `GOOGLE_API_KEY`: Required for the Gemini reasoning engine.

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
   # Add your GOOGLE_API_KEY
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

## 🛠️ Troubleshooting: macOS Docker Keychain Issue

If provisioning to a macOS worker fails with `keychain cannot be accessed`, Docker is trying to use the interactive macOS keychain in a non-interactive SSH session.

**Fix:** Run this command on the **remote macOS worker** to disable the credential helper for the automated session:
```bash
mkdir -p ~/.docker
echo '{"credsStore": ""}' > ~/.docker/config.json
```
Alternatively, the Genesis node attempts to bypass this by setting environment variables during deployment.

## 🏗️ Project Structure

- `main.py`: Entry point for the Genesis CNC Node.
- `central_node/`: Docker Compose and Worker logic for the remote execution environment.
- `src/analyzer/`: Intent parsing and infrastructure selection (Gemini 3 Flash).
- `src/iac/`: Pulumi SSH/Command orchestration for remote provisioning.
- `src/orchestrator/`: Temporal client and task scheduler.
- `src/memory/`: Tiered L1/L2/L3 memory store clients.

