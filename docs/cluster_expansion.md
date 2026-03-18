# AI Orchestration Cluster Expansion Guide

This guide provides technical details on how to scale your AI Orchestration system by adding more worker nodes (Execution Plane) to the cluster.

---

## 🏗️ Architecture Overview

The system follows a three-plane architecture:
1.  **Genesis Node (Thin CNC)**: Typically a low-power device (e.g., Raspberry Pi 3) that parses user intent and delegates tasks.
2.  **Control Plane (Central Node)**: Hosts the persistent core services:
    *   **Temporal Server (v1.20+)**: Workflow engine and task queue.
    *   **Qdrant**: Vector database for semantic memory.
    *   **Redis**: L1 ephemeral cache.
    *   **Postgres**: Storage for Temporal states.
3.  **Execution Plane (Worker Nodes)**: One or more machines that pull and execute tasks.

Adding another machine to the cluster usually means adding an **Execution Plane Worker**.

---

## 🛠️ Step-by-Step Expansion

### 1. Network Connectivity

The new machine must be able to communicate with the **Central Node**'s IP address.

| Service | Port | Description |
| :--- | :--- | :--- |
| **Temporal** | `7233` | Task queue and workflow gRPC interface. |
| **Qdrant** | `6333` | Vector search API. |
| **Redis** | `6379` | Fast context cache. |

> [!IMPORTANT]
> Ensure your firewall (e.g., `ufw`, `iptables`, or cloud security groups) allows inbound traffic on these ports at the **Central Node** from the **New Worker's IP**.

### 2. Environment Setup

On the new machine:

1.  **Clone the Repository**:
    ```bash
    git clone <your-repository-url>
    cd ai-orchestration-project
    ```

2.  **Install Python Dependencies**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configure API Keys**:
    Create a `.env` file and add your provider keys so the agent can use LLM models locally:
    ```env
    GOOGLE_API_KEY=your_key
    OPENAI_API_KEY=your_key
    ANTHROPIC_API_KEY=your_key
    ```

### 3. Connection Settings

Tell the new worker where the **Control Plane** is located.

#### Option A: Using Environment Variables (Recommended)
Add these to your `.env` file on the new machine:
```env
TEMPORAL_HOST_URL=192.168.100.x:7233
QDRANT_URL=http://192.168.100.x:6333
REDIS_HOST=192.168.100.x
```

#### Option B: Using `config/settings.yaml`
Update the `temporal` section:
```yaml
temporal:
  host: "192.168.100.x"
  port: 7233
```

### 4. Verification

Run the worker script:
```bash
python central_node/worker.py
```

If successful, you should see output similar to:
`Connecting to Temporal at 192.168.100.x:7233...`
`Worker started. Listening on 'ai-orchestration-queue'...`

---

## 🚀 Scaling Strategies

### Horizontal Scaling
Since the Workers are **stateless** and pull tasks from a shared Temporal queue, adding more machines automatically increases the system's throughput. 

### Worker Specialization
You can run workers on specific machines with different environment variables (e.g., a machine with a powerful GPU for local models, or a machine with specialized local tools). To do this:
1. Modify the `task_queue` in `worker.py` (e.g., `gpu-queue`).
2. Update the `Scheduler` logic in the Genesis node to route specific tasks to that queue.

---

## 🔍 Troubleshooting

- **Timeout connecting to Temporal**: Check if the Central Node's firewall allows port `7233`. Try `telnet <ip> 7233`.
- **404 from Qdrant**: Ensure `QDRANT_URL` includes `http://` and the correct port.
- **Worker Crashes on Start**: Check that all providers defined in `config/profiles.yaml` have their respective API keys set.
