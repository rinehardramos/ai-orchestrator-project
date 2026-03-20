#!/usr/bin/env bash

# AI Orchestrator Unified Bootstrap Script
# This script configures a machine as a Controller, Worker, or CNC node.

set -e

# --- Configuration & Defaults ---
ENV_FILE=".env"
NETWORK_NAME="worker_ai-network"
COMPOSE_WORKER_FILE="src/execution/worker/docker-compose.yml"
COMPOSE_CNC_FILE="docker-compose.cnc.yml"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}   🚀 AI Orchestrator: Unified Machine Bootstrap${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# --- Dependency Check ---
check_dependency() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}❌ Error: $1 is not installed.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ $1 found.${NC}"
}

check_dependency "docker"
check_dependency "python3"

# Check docker-compose vs 'docker compose'
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}❌ Error: docker compose is not installed.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ $DOCKER_COMPOSE found.${NC}"

# --- Helper: Update .env ---
update_env() {
    local key=$1
    local value=$2
    if [ ! -f "$ENV_FILE" ]; then
        touch "$ENV_FILE"
    fi
    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i.bak "s|^$key=.*|$key=$value|" "$ENV_FILE"
    else
        echo "$key=$value" >> "$ENV_FILE"
    fi
}

prompt_if_empty() {
    local key=$1
    local prompt_text=$2
    local existing_val=$(grep "^$key=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
    if [ -z "$existing_val" ]; then
        echo -n -e "${YELLOW}$prompt_text: ${NC}"
        read -r input_val
        if [ -n "$input_val" ]; then
            update_env "$key" "$input_val"
        fi
    fi
}

# --- Health Checks ---
verify_service() {
    local name=$1
    local type=$2 # "container" or "url"
    local target=$3
    local max_retries=10
    local count=0

    echo -n -e "${BLUE}🔍 Checking $name... ${NC}"

    while [ $count -lt $max_retries ]; do
        case $type in
            container)
                if [ "$(docker inspect -f '{{.State.Status}}' "$target" 2>/dev/null)" == "running" ]; then
                    echo -e "${GREEN}UP${NC}"
                    return 0
                fi
                ;;
            url)
                if curl -sSf "$target" &> /dev/null; then
                    echo -e "${GREEN}READY${NC}"
                    return 0
                fi
                # Special case for Temporal gRPC port which might not respond to HTTP curl
                if echo > /dev/tcp/${target#*://*} 2>/dev/null; then
                     echo -e "${GREEN}REACHABLE (PORT)${NC}"
                     return 0
                fi
                ;;
        esac
        count=$((count + 1))
        echo -n "."
        sleep 2
    done

    echo -e "${RED}FAILED${NC}"
    return 1
}

verify_role_health() {
    local choice=$1
    echo -e "\n${YELLOW}🛠️ Verifying Services for Role #$choice...${NC}"
    sleep 3 # Give docker a moment to breath

    case $choice in
        1) # Full Stack
            verify_service "Temporal" "container" "temporal"
            verify_service "Qdrant" "url" "http://localhost:6333/health"
            verify_service "Redis" "container" "redis"
            verify_service "Postgres" "container" "postgres"
            verify_service "AI Worker" "container" "ai-worker"
            verify_service "CNC Genesis" "container" "cnc-genesis"
            verify_service "Telegram Ingress" "container" "telegram-ingress"
            ;;
        2) # Controller
            verify_service "Temporal" "container" "temporal"
            verify_service "Qdrant" "url" "http://localhost:6333/health"
            verify_service "Redis" "container" "redis"
            verify_service "Postgres" "container" "postgres"
            ;;
        3) # Worker
            local t_host=$(grep "^TEMPORAL_HOST_URL=" "$ENV_FILE" | cut -d'=' -f2-)
            local q_url=$(grep "^QDRANT_URL=" "$ENV_FILE" | cut -d'=' -f2-)
            verify_service "Remote Temporal" "url" "$t_host"
            verify_service "Remote Qdrant" "url" "$q_url/health"
            verify_service "Local AI Worker" "container" "ai-worker"
            ;;
        4) # CNC
            local t_host=$(grep "^TEMPORAL_HOST=" "$ENV_FILE" | cut -d'=' -f2-)
            verify_service "Remote Temporal" "url" "http://$t_host:7233"
            verify_service "CNC Genesis" "container" "cnc-genesis"
            verify_service "Telegram Ingress" "container" "telegram-ingress"
            ;;
    esac
}

# --- Role Selection ---
echo -e "\n${BLUE}Select the role for this machine:${NC}"
echo "1) Full Stack (Controller + Worker + CNC)"
echo "2) Controller (Temporal, Qdrant, Redis, Postgres)"
echo "3) Worker (Task Execution only)"
echo "4) CNC (Command interface & Telegram Monitor)"
echo -n -e "${YELLOW}Enter choice [1-4]: ${NC}"
read -r ROLE_CHOICE

# --- Networking ---
# Create network if it doesn't exist
if ! docker network ls | grep -q "$NETWORK_NAME"; then
    echo -e "${BLUE}🌐 Creating docker network: $NETWORK_NAME...${NC}"
    docker network create "$NETWORK_NAME"
fi

# --- Main Configuration Logic ---
case $ROLE_CHOICE in
    1)
        echo -e "${GREEN}Configuring Full Stack...${NC}"
        prompt_if_empty "GOOGLE_API_KEY" "Enter Google API Key"
        prompt_if_empty "OPENAI_API_KEY" "Enter OpenAI API Key"
        prompt_if_empty "ANTHROPIC_API_KEY" "Enter Anthropic API Key"
        prompt_if_empty "TELEGRAM_BOT_TOKEN" "Enter Telegram Bot Token"
        prompt_if_empty "TELEGRAM_CHAT_ID" "Enter Telegram Chat ID"
        
        echo -e "${BLUE}🚢 Launching Core Services & Worker...${NC}"
        $DOCKER_COMPOSE -f "$COMPOSE_WORKER_FILE" up -d
        
        echo -e "${BLUE}🚢 Launching CNC Services...${NC}"
        $DOCKER_COMPOSE -f "$COMPOSE_CNC_FILE" up -d
        ;;
    2)
        echo -e "${GREEN}Configuring Controller only...${NC}"
        # Start core services but not the worker
        echo -e "${BLUE}🚢 Launching Core Services...${NC}"
        $DOCKER_COMPOSE -f "$COMPOSE_WORKER_FILE" up -d temporal postgres qdrant redis
        ;;
    3)
        echo -e "${GREEN}Configuring Worker only...${NC}"
        prompt_if_empty "TEMPORAL_HOST_URL" "Enter Temporal Host (e.g., 192.168.1.10:7233)"
        prompt_if_empty "QDRANT_URL" "Enter Qdrant URL (e.g., http://192.168.1.10:6333)"
        prompt_if_empty "GOOGLE_API_KEY" "Enter Google API Key"
        
        echo -e "${BLUE}🚢 Launching AI Worker...${NC}"
        $DOCKER_COMPOSE -f "$COMPOSE_WORKER_FILE" up -d ai-worker
        ;;
    4)
        echo -e "${GREEN}Configuring CNC node...${NC}"
        prompt_if_empty "TEMPORAL_HOST" "Enter Controller IP (for Temporal/Qdrant)"
        # Update existing hosts to the new IP if provided
        local ctrl_ip=$(grep '^TEMPORAL_HOST=' "$ENV_FILE" | cut -d'=' -f2-)
        update_env "QDRANT_HOST" "$ctrl_ip"
        update_env "REDIS_HOST" "$ctrl_ip"
        prompt_if_empty "TELEGRAM_BOT_TOKEN" "Enter Telegram Bot Token"
        prompt_if_empty "TELEGRAM_CHAT_ID" "Enter Telegram Chat ID"
        
        echo -e "${BLUE}🚢 Launching CNC Tools...${NC}"
        $DOCKER_COMPOSE -f "$COMPOSE_CNC_FILE" up -d
        ;;
    *)
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
        ;;
esac

# Run Health Checks
verify_role_health "$ROLE_CHOICE"

echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   ✅ Bootstrap Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "Monitor services: ${BLUE}$DOCKER_COMPOSE ps${NC}"
echo -e "View logs:       ${BLUE}$DOCKER_COMPOSE logs -f --tail=100${NC}"
