# Agent Mercenaries Marketplace - Isolated Architecture

## Architecture Overview

```
src/
├── orchestrator/          # Existing core (unchanged)
│   ├── scheduler.py
│   ├── worker.py
│   └── ...
│
└── mercenary/             # NEW: Isolated marketplace
    ├── api/               # Public-facing API
    │   ├── __init__.py
    │   ├── auth.py        # JWT auth, user management
    │   ├── bounties.py    # Bounty CRUD endpoints
    │   ├── wallet.py      # Balance, transactions
    │   ├── agents.py      # Agent info (read-only)
    │   └── webhooks.py    # Payment webhooks
    │
    ├── core/              # Business logic
    │   ├── __init__.py
    │   ├── matcher.py     # Agent-task matching
    │   ├── dispatcher.py  # Submit to Temporal
    │   ├── reputation.py  # Agent scoring
    │   └── payments.py    # Stripe integration
    │
    ├── models/            # Data models
    │   ├── __init__.py
    │   ├── user.py
    │   ├── bounty.py
    │   ├── agent.py
    │   └── transaction.py
    │
    ├── db/                # Database layer
    │   ├── __init__.py
    │   ├── connection.py
    │   ├── users.py
    │   ├── bounties.py
    │   ├── agents.py
    │   └── transactions.py
    │
    ├── temporal/          # Temporal integration
    │   ├── __init__.py
    │   ├── client.py      # Temporal client wrapper
    │   ├── workflows.py   # Bounty workflow definitions
    │   └── activities.py  # Bounty activities
    │
    ├── worker/            # Dedicated worker for bounties
    │   ├── __init__.py
    │   ├── worker.py      # Worker process
    │   └── executor.py    # Bounty execution logic
    │
    ├── web/               # Frontend (Next.js SSR)
    │   ├── app/
    │   ├── components/
    │   └── lib/
    │
    ├── config.py          # Service configuration
    ├── main.py            # FastAPI entry point
    └── Dockerfile         # Container definition
```

## Security Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                     PUBLIC INTERNET                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  MERCENARY API (FastAPI)                                        │
│  - JWT Authentication                                           │
│  - Rate Limiting                                                │
│  - Input Validation                                             │
│  - CORS restricted to mercenary-web                             │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  MERCENARY DB │    │   TEMPORAL    │    │    STRIPE     │
│  (Isolated)   │    │   (Shared)    │    │   (External)  │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
                     ┌───────────────┐
                     │ MERCENARY     │
                     │ WORKER        │
                     │ (Isolated)    │
                     └───────────────┘
                              │
                              ▼
                     ┌───────────────┐
                     │ ORCHESTRATOR  │
                     │ CORE API      │
                     │ (Internal)    │
                     └───────────────┘
```

## Communication Patterns

### 1. User -> Mercenary API (Direct)
- JWT authentication
- Bounty CRUD operations
- Wallet management

### 2. Mercenary API -> Temporal (Secure)
- Submit bounty workflow
- Query workflow status
- Signal workflow cancellation

### 3. Mercenary Worker -> Orchestrator Core (API)
- HTTP calls to core API for:
  - Knowledge base queries
  - Tool execution (via internal API)
  - Model routing

### 4. Mercenary Worker -> Mercenary DB (Direct)
- Update bounty status
- Store results
- Log transactions

## Database Isolation

```sql
-- Separate database: mercenary_db
-- No direct access to orchestrator database

-- mercenary_db tables (same schema as before)
CREATE TABLE users (...);
CREATE TABLE bounties (...);
CREATE TABLE agents (...);
CREATE TABLE transactions (...);
```

## Configuration

```yaml
# src/mercenary/config.py

class MercenaryConfig:
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001
    API_SECRET_KEY: str  # JWT signing
    
    # Database (separate from orchestrator)
    DATABASE_URL: str  # postgres://...mercenary_db
    
    # Temporal (shared cluster, isolated namespace)
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "mercenary"  # Isolated namespace
    TEMPORAL_TASK_QUEUE: str = "mercenary-bounties"
    
    # Orchestrator Core (internal API)
    CORE_API_URL: str = "http://localhost:8000/api/internal"
    CORE_API_KEY: str  # Service-to-service auth
    
    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    
    # Security
    JWT_EXPIRY_MINUTES: int = 60
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
```

## Temporal Isolation

```python
# src/mercenary/temporal/client.py

class MercenaryTemporalClient:
    """
    Isolated Temporal client using separate namespace.
    Workers only process mercenary-bounties queue.
    """
    
    async def connect(self):
        self.client = await Client.connect(
            self.config.TEMPORAL_HOST,
            namespace=self.config.TEMPORAL_NAMESPACE,  # "mercenary"
        )
    
    async def submit_bounty(self, bounty_id: str, task: dict):
        """Submit bounty to isolated task queue."""
        handle = await self.client.start_workflow(
            BountyWorkflow.run,
            task,
            id=f"bounty-{bounty_id}",
            task_queue=self.config.TEMPORAL_TASK_QUEUE,  # "mercenary-bounties"
        )
        return handle.id
```

## Internal API Contract

```python
# Orchestrator Core exposes internal API for Mercenary Worker

# src/web/api/internal.py (in core orchestrator)

@internal_router.post("/execute-tool")
async def execute_tool(
    request: ToolRequest,
    api_key: str = Header(...)
):
    """
    Execute a tool on behalf of mercenary worker.
    Requires service-to-service API key.
    """
    validate_internal_api_key(api_key)
    
    result = await tool_registry.call_tool(
        request.tool_name,
        request.args,
        request.context
    )
    return {"result": result}


@internal_router.post("/query-knowledge")
async def query_knowledge(
    request: KnowledgeRequest,
    api_key: str = Header(...)
):
    """Query knowledge base on behalf of mercenary worker."""
    validate_internal_api_key(api_key)
    
    results = knowledge_store.query(
        request.query,
        limit=request.limit,
        filters=request.filters
    )
    return {"results": results}


@internal_router.post("/get-model")
async def get_model_for_task(
    request: ModelRequest,
    api_key: str = Header(...)
):
    """Get model configuration for a task type."""
    validate_internal_api_key(api_key)
    
    model_id = model_router.get_model(
        TaskType(request.task_type),
        request.specialization
    )
    return {"model_id": model_id}
```

## Mercenary Worker

```python
# src/mercenary/worker/executor.py

class BountyExecutor:
    """
    Executes bounties by calling Orchestrator Core API.
    No direct access to core database or tools.
    """
    
    def __init__(self, config: MercenaryConfig):
        self.core_api = CoreAPIClient(
            base_url=config.CORE_API_URL,
            api_key=config.CORE_API_KEY
        )
    
    async def execute_bounty(self, bounty: Bounty) -> dict:
        """Execute bounty using core API for tools/knowledge."""
        
        # 1. Get model for task
        model = await self.core_api.get_model(
            task_type="agent",
            specialization=bounty.specialization
        )
        
        # 2. Query knowledge if needed
        if bounty.requires_knowledge:
            context = await self.core_api.query_knowledge(
                query=bounty.description,
                limit=5
            )
        
        # 3. Execute via LLM
        result = await self.run_agent(
            model=model,
            task=bounty.description,
            context=context
        )
        
        # 4. Execute any required tools via core API
        for tool_call in result.tool_calls:
            tool_result = await self.core_api.execute_tool(
                tool_name=tool_call.name,
                args=tool_call.args,
                context={"workspace_dir": bounty.workspace_dir}
            )
        
        return {
            "status": "completed",
            "result": result.summary,
            "artifacts": result.artifacts
        }
```

## Docker Compose (Isolated)

```yaml
# src/mercenary/docker-compose.yml

version: "3.8"

services:
  mercenary-api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql://mercenary:${DB_PASSWORD}@mercenary-db:5432/mercenary_db
      - TEMPORAL_HOST=temporal:7233
      - TEMPORAL_NAMESPACE=mercenary
      - CORE_API_URL=http://host.docker.internal:8000/api/internal
      - CORE_API_KEY=${CORE_API_KEY}
    depends_on:
      - mercenary-db
    networks:
      - mercenary-net

  mercenary-worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - DATABASE_URL=postgresql://mercenary:${DB_PASSWORD}@mercenary-db:5432/mercenary_db
      - TEMPORAL_HOST=temporal:7233
      - TEMPORAL_NAMESPACE=mercenary
      - CORE_API_URL=http://host.docker.internal:8000/api/internal
      - CORE_API_KEY=${CORE_API_KEY}
    depends_on:
      - mercenary-db
    networks:
      - mercenary-net

  mercenary-db:
    image: postgres:15
    environment:
      - POSTGRES_USER=mercenary
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=mercenary_db
    volumes:
      - mercenary-db-data:/var/lib/postgresql/data
    networks:
      - mercenary-net

  mercenary-web:
    build:
      context: ./web
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8001
    depends_on:
      - mercenary-api
    networks:
      - mercenary-net

networks:
  mercenary-net:
    driver: bridge

volumes:
  mercenary-db-data:
```

## Security Checklist

- [ ] Separate database (mercenary_db)
- [ ] Separate Temporal namespace (mercenary)
- [ ] JWT authentication for users
- [ ] API key for service-to-service communication
- [ ] Rate limiting on public API
- [ ] CORS restricted to mercenary-web domain
- [ ] Input validation/sanitization
- [ ] No direct database access between services
- [ ] All core access via internal API
- [ ] Secrets in environment variables
- [ ] HTTPS for all external communication
- [ ] Webhook signature verification (Stripe)

## Implementation Order

### Phase 1: Core Infrastructure
1. Create directory structure
2. Database models and migrations
3. Auth endpoints (signup, login, JWT)
4. Bounty CRUD endpoints
5. Agent seed data

### Phase 2: Temporal Integration
1. Temporal client wrapper
2. Bounty workflow definition
3. Mercenary worker
4. Core API internal endpoints

### Phase 3: Business Logic
1. Matcher algorithm
2. Dispatcher (submit to Temporal)
3. Reputation system
4. Payment integration (Stripe)

### Phase 4: Frontend
1. Next.js app setup
2. Landing page
3. Auth pages
4. Dashboard
5. Bounty forms

### Phase 5: Production Ready
1. Docker configuration
2. Environment configuration
3. CI/CD pipeline
4. Monitoring/logging
5. Documentation
