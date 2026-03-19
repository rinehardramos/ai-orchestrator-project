#!/bin/bash

# Exit on any error
set -e

echo "🚀 Starting Pure Orchestrator Setup (No Docker)..."

# 1. Update and install system dependencies (Python & Networking only)
echo "📦 Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv curl redis-tools

# 2. Set up Python Virtual Environment
echo "🐍 Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created venv"
fi

# 3. Install Python requirements
echo "📥 Installing Python packages..."
source venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    # Filter out any docker-specific python libs if they exist
    grep -v "docker" requirements.txt > requirements_pure.txt
    pip install -r requirements_pure.txt
    rm requirements_pure.txt
    echo "✅ Installed filtered requirements"
else
    echo "⚠️ requirements.txt not found! Installing core packages manually..."
    pip install google-genai pyyaml pydantic python-dotenv pulumi celery redis boto3
fi

# 4. Install Pulumi CLI (For remote provisioning)
echo "🏗️ Checking for Pulumi CLI..."
if ! command -v pulumi &> /dev/null; then
    echo "Installing Pulumi..."
    curl -fsSL https://get.pulumi.com | sh
    export PATH=$PATH:$HOME/.pulumi/bin
    
    if ! grep -q ".pulumi/bin" ~/.bashrc; then
        echo 'export PATH=$PATH:$HOME/.pulumi/bin' >> ~/.bashrc
        echo "✅ Added Pulumi to ~/.bashrc"
    fi
else
    echo "✅ Pulumi already installed"
fi

# 5. Verify Installation
echo "🔍 Verifying installation..."
python3 --version
source venv/bin/activate && python3 -c "import google.genai; import langgraph; import pulumi; print('✅ Core Orchestrator dependencies verified')"
pulumi version

# 6. Install Telegram Monitor as a systemd service (Optional/Interactive)
echo "🤖 Do you want to install the Telegram Ingress Monitor as a systemd service? (y/N)"
read -r INSTALL_TG
if [[ "$INSTALL_TG" =~ ^[Yy]$ ]]; then
    echo "📦 Installing Telegram Monitor Service..."
    SERVICE_PATH="/etc/systemd/system/telegram-monitor.service"
    
    # Use the absolute path from current directory
    REPO_DIR=$(pwd)
    
    # Update the service file with correct working directory and user
    sed "s|/home/pi/Projects/ai-orchestration-project|$REPO_DIR|g" "$REPO_DIR/scripts/telegram-monitor.service" | \
    sed "s|User=pi|User=$(whoami)|g" > telegram-monitor.service.tmp
    
    sudo mv telegram-monitor.service.tmp "$SERVICE_PATH"
    sudo systemctl daemon-reload
    sudo systemctl enable telegram-monitor
    sudo systemctl start telegram-monitor
    echo "✅ Telegram Monitor Service installed and started."
    echo "   View logs: journalctl -u telegram-monitor -f"
fi

echo "------------------------------------------------"
echo "✨ Orchestrator Setup Complete!"
echo "Note: This system is now a 'Pure Orchestrator'."
echo "It will delegate tasks to remote workers via Pulumi/SSH."
echo "------------------------------------------------"
