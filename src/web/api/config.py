import re
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
import os

config_router = APIRouter(prefix="/api/config")


class RoutingUpdate(BaseModel):
    task_routing: Dict[str, Any]


class SpecializationsUpdate(BaseModel):
    specializations: Dict[str, Any]


class AgentDefaultsUpdate(BaseModel):
    agent_defaults: Dict[str, Any]


class InfrastructureUpdate(BaseModel):
    infrastructure: Dict[str, Any]


class ClusterUpdate(BaseModel):
    nodes: List[Dict[str, Any]]


class DatabaseSettings(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None


class ModelCreate(BaseModel):
    id: str
    provider: str
    cost_per_1k_tokens: Optional[float] = 0.0
    context_window: Optional[int] = 8192
    reasoning_capability: Optional[str] = "medium"
    speed: Optional[str] = "fast"

    @field_validator('id')
    @classmethod
    def validate_id(cls, v, info):
        provider = info.data.get('provider', '')
        
        # OpenRouter requires provider/model-name format
        if provider == 'openrouter':
            if not re.match(r'^[a-z0-9-]+/[a-z0-9-_.]+$', v):
                raise ValueError('OpenRouter model ID must be in format: provider/model-name (e.g., openai/gpt-4o)')
            return v
        
        # All other providers: allow flexible model ID (can be model-name or org/model)
        if not re.match(r'^[a-z0-9-_.]+(/[a-z0-9-_.]+)?$', v):
            raise ValueError('Model ID must be lowercase alphanumeric, hyphens, underscores, or dots (optionally: org/model)')
        return v


class ModelUpdate(BaseModel):
    provider: Optional[str] = None
    cost_per_1k_tokens: Optional[float] = None
    context_window: Optional[int] = None
    reasoning_capability: Optional[str] = None
    speed: Optional[str] = None


class RoutingEntryCreate(BaseModel):
    task_name: str
    model: str
    provider: Optional[str] = None

    @field_validator('task_name')
    @classmethod
    def validate_task_name(cls, v):
        if not re.match(r'^[a-z_]+$', v):
            raise ValueError('Task name must be lowercase letters and underscores only')
        return v


class SpecializationCreate(BaseModel):
    name: str
    model: str
    provider: Optional[str] = "google"
    allowed_tools: List[str] = []

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not re.match(r'^[a-z_]+$', v):
            raise ValueError('Specialization name must be lowercase letters and underscores only')
        return v


class SpecializationUpdate(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    allowed_tools: Optional[List[str]] = None


def _get_loader():
    from src.config_db import get_loader
    return get_loader()


def _check_model_usage(model_id: str) -> Dict[str, List[str]]:
    """Check if a model is used in routing or specializations."""
    loader = _get_loader()
    usage = {"routing": [], "specializations": []}
    
    routing = loader.get("profiles", "task_routing", {})
    for task, config in routing.items():
        if config.get("model") == model_id:
            usage["routing"].append(task)
    
    specs = loader.load_namespace("specializations")
    for name, config in specs.items():
        if config.get("model") == model_id:
            usage["specializations"].append(name)
    
    return usage


@config_router.get("/routing")
async def get_routing():
    return _get_loader().get("profiles", "task_routing", {})


@config_router.put("/routing")
async def update_routing(payload: RoutingUpdate):
    loader = _get_loader()
    data = loader.load_namespace("profiles")
    data["task_routing"] = payload.task_routing
    loader.save_namespace("profiles", data)
    return {"status": "success"}


@config_router.post("/routing/entries")
async def add_routing_entry(payload: RoutingEntryCreate):
    loader = _get_loader()
    routing = loader.get("profiles", "task_routing", {})
    
    if payload.task_name in routing:
        raise HTTPException(status_code=400, detail=f"Task '{payload.task_name}' already exists")
    
    models = loader.get("profiles", "models", [])
    model_ids = [m["id"] for m in models]
    if payload.model not in model_ids:
        raise HTTPException(status_code=400, detail=f"Model '{payload.model}' not found. Available: {model_ids}")
    
    provider = payload.provider
    if not provider:
        model_info = next((m for m in models if m["id"] == payload.model), None)
        provider = model_info.get("provider", "google") if model_info else "google"
    
    routing[payload.task_name] = {
        "model": payload.model,
        "provider": provider
    }
    
    data = loader.load_namespace("profiles")
    data["task_routing"] = routing
    loader.save_namespace("profiles", data)
    return {"status": "success", "task_name": payload.task_name}


@config_router.delete("/routing/{task_name}")
async def delete_routing_entry(task_name: str):
    loader = _get_loader()
    routing = loader.get("profiles", "task_routing", {})
    
    if task_name not in routing:
        raise HTTPException(status_code=404, detail=f"Task '{task_name}' not found")
    
    del routing[task_name]
    data = loader.load_namespace("profiles")
    data["task_routing"] = routing
    loader.save_namespace("profiles", data)
    return {"status": "success"}


@config_router.get("/models")
async def get_models():
    return _get_loader().get("profiles", "models", [])


@config_router.post("/models")
async def add_model(payload: ModelCreate):
    loader = _get_loader()
    models = loader.get("profiles", "models", [])
    
    existing_ids = [m["id"] for m in models]
    if payload.id in existing_ids:
        raise HTTPException(status_code=400, detail=f"Model '{payload.id}' already exists")
    
    new_model = {
        "id": payload.id,
        "provider": payload.provider,
        "cost_per_1k_tokens": payload.cost_per_1k_tokens,
        "context_window": payload.context_window,
        "reasoning_capability": payload.reasoning_capability,
        "speed": payload.speed
    }
    
    models.append(new_model)
    data = loader.load_namespace("profiles")
    data["models"] = models
    loader.save_namespace("profiles", data)
    return {"status": "success", "model": new_model}


@config_router.put("/models/{model_id:path}")
async def update_model(model_id: str, payload: ModelUpdate):
    loader = _get_loader()
    models = loader.get("profiles", "models", [])
    
    model_index = None
    for i, m in enumerate(models):
        if m["id"] == model_id:
            model_index = i
            break
    
    if model_index is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    
    if payload.provider is not None:
        models[model_index]["provider"] = payload.provider
    if payload.cost_per_1k_tokens is not None:
        models[model_index]["cost_per_1k_tokens"] = payload.cost_per_1k_tokens
    if payload.context_window is not None:
        models[model_index]["context_window"] = payload.context_window
    if payload.reasoning_capability is not None:
        models[model_index]["reasoning_capability"] = payload.reasoning_capability
    if payload.speed is not None:
        models[model_index]["speed"] = payload.speed
    
    data = loader.load_namespace("profiles")
    data["models"] = models
    loader.save_namespace("profiles", data)
    return {"status": "success"}


@config_router.delete("/models/{model_id:path}")
async def delete_model(model_id: str):
    usage = _check_model_usage(model_id)
    
    if usage["routing"] or usage["specializations"]:
        usage_details = []
        if usage["routing"]:
            usage_details.append(f"routing tasks: {', '.join(usage['routing'])}")
        if usage["specializations"]:
            usage_details.append(f"specializations: {', '.join(usage['specializations'])}")
        
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete model '{model_id}'. It is used by {'; '.join(usage_details)}"
        )
    
    loader = _get_loader()
    models = loader.get("profiles", "models", [])
    
    new_models = [m for m in models if m["id"] != model_id]
    
    if len(new_models) == len(models):
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    
    data = loader.load_namespace("profiles")
    data["models"] = new_models
    loader.save_namespace("profiles", data)
    return {"status": "success"}


@config_router.get("/models/{model_id:path}/usage")
async def get_model_usage(model_id: str):
    return _check_model_usage(model_id)


@config_router.get("/specializations")
async def get_specializations():
    return _get_loader().load_namespace("specializations")


@config_router.put("/specializations")
async def update_specializations(payload: SpecializationsUpdate):
    loader = _get_loader()
    loader.save_namespace("specializations", payload.specializations)
    return {"status": "success"}


@config_router.post("/specializations")
async def add_specialization(payload: SpecializationCreate):
    loader = _get_loader()
    specs = loader.load_namespace("specializations")
    
    if payload.name in specs:
        raise HTTPException(status_code=400, detail=f"Specialization '{payload.name}' already exists")
    
    models = loader.get("profiles", "models", [])
    model_ids = [m["id"] for m in models]
    if payload.model not in model_ids:
        raise HTTPException(status_code=400, detail=f"Model '{payload.model}' not found")
    
    specs[payload.name] = {
        "model": payload.model,
        "provider": payload.provider,
        "allowed_tools": payload.allowed_tools
    }
    
    loader.save_namespace("specializations", specs)
    return {"status": "success", "name": payload.name}


@config_router.put("/specializations/{name}")
async def update_specialization(name: str, payload: SpecializationUpdate):
    loader = _get_loader()
    specs = loader.load_namespace("specializations")
    
    if name not in specs:
        raise HTTPException(status_code=404, detail=f"Specialization '{name}' not found")
    
    if payload.model is not None:
        models = loader.get("profiles", "models", [])
        model_ids = [m["id"] for m in models]
        if payload.model not in model_ids:
            raise HTTPException(status_code=400, detail=f"Model '{payload.model}' not found")
        specs[name]["model"] = payload.model
    
    if payload.provider is not None:
        specs[name]["provider"] = payload.provider
    
    if payload.allowed_tools is not None:
        specs[name]["allowed_tools"] = payload.allowed_tools
    
    loader.save_namespace("specializations", specs)
    return {"status": "success"}


@config_router.delete("/specializations/{name}")
async def delete_specialization(name: str):
    loader = _get_loader()
    specs = loader.load_namespace("specializations")
    
    if name not in specs:
        raise HTTPException(status_code=404, detail=f"Specialization '{name}' not found")
    
    del specs[name]
    loader.save_namespace("specializations", specs)
    return {"status": "success"}


@config_router.get("/agent-defaults")
async def get_agent_defaults():
    return _get_loader().load_namespace("jobs")


@config_router.put("/agent-defaults")
async def update_agent_defaults(payload: AgentDefaultsUpdate):
    loader = _get_loader()
    loader.save_namespace("jobs", payload.agent_defaults)
    return {"status": "success"}


@config_router.get("/infrastructure")
async def get_infrastructure():
    return _get_loader().load_namespace("infrastructure")


@config_router.put("/infrastructure")
async def update_infrastructure(payload: InfrastructureUpdate):
    loader = _get_loader()
    loader.save_namespace("infrastructure", payload.infrastructure)
    return {"status": "success"}


@config_router.get("/cluster")
async def get_cluster():
    return _get_loader().get("cluster_nodes", "nodes", [])


@config_router.put("/cluster")
async def update_cluster(payload: ClusterUpdate):
    loader = _get_loader()
    data = {"nodes": payload.nodes}
    loader.save_namespace("cluster_nodes", data)
    return {"status": "success"}


@config_router.get("/database")
async def get_database_settings():
    loader = _get_loader()
    db_config = loader.load_namespace("database")
    return {
        "host": db_config.get("host", "localhost"),
        "port": db_config.get("port", 5432),
        "database": db_config.get("database", "orchestrator"),
        "user": db_config.get("user", "temporal"),
        "password": "••••••••" if db_config.get("password") else ""
    }


@config_router.put("/database")
async def update_database_settings(payload: DatabaseSettings):
    loader = _get_loader()
    db_config = {}
    if payload.host:
        db_config["host"] = payload.host
    if payload.port:
        db_config["port"] = payload.port
    if payload.database:
        db_config["database"] = payload.database
    if payload.user:
        db_config["user"] = payload.user
    if payload.password and payload.password != "••••••••":
        db_config["password"] = payload.password
    
    existing = loader.load_namespace("database")
    existing.update(db_config)
    loader.save_namespace("database", existing)
    return {"status": "success"}


@config_router.get("/database/status")
async def get_database_status():
    loader = _get_loader()
    try:
        conn = loader._get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM tools")
        tool_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM app_config")
        config_count = cur.fetchone()[0]
        
        cur.execute("SELECT value FROM system_state WHERE key = 'setup_complete'")
        row = cur.fetchone()
        setup_complete = row[0] == 'true' if row else False
        
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = cur.fetchone()[0]
        
        return {
            "connected": True,
            "database": loader.database_url.split("/")[-1].split("?")[0] if loader.database_url else "unknown",
            "tables": tables,
            "tool_count": tool_count,
            "config_count": config_count,
            "setup_complete": setup_complete
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }


@config_router.post("/database/test")
async def test_database_connection(payload: DatabaseSettings):
    try:
        import psycopg2
        conn_str = f"host={payload.host or 'localhost'} port={payload.port or 5432} dbname={payload.database or 'orchestrator'} user={payload.user or 'temporal'} password={payload.password or ''}"
        conn = psycopg2.connect(conn_str, connect_timeout=5)
        conn.close()
        return {"connected": True}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@config_router.post("/database/migrate")
async def run_migrations():
    import subprocess
    result = subprocess.run(
        ["python", "scripts/migrate.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": os.environ.get("DATABASE_URL", "")}
    )
    if result.returncode == 0:
        return {"status": "success", "message": "Migrations completed"}
    else:
        return {"status": "error", "message": result.stderr or result.stdout}


@config_router.post("/database/seed")
async def seed_config():
    import subprocess
    result = subprocess.run(
        ["python", "scripts/seed_noncritical_config.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": os.environ.get("DATABASE_URL", "")}
    )
    if result.returncode == 0:
        return {"status": "success", "message": "Configuration seeded"}
    else:
        return {"status": "error", "message": result.stderr or result.stdout}


class EmbeddingConfig(BaseModel):
    model: str
    provider: str
    dim: Optional[int] = 768


class DualEmbeddingConfig(BaseModel):
    text: Optional[EmbeddingConfig] = None
    code: Optional[EmbeddingConfig] = None


@config_router.get("/embeddings")
async def get_embedding_config():
    """Get dual embedding model configuration."""
    loader = _get_loader()
    task_routing = loader.get("profiles", "task_routing", {})
    
    defaults = {
        "text": {"model": "nomic-embed-text-v1.5", "provider": "lmstudio", "dim": 768},
        "code": {"model": "nomic-embed-code", "provider": "lmstudio", "dim": 3584}
    }
    
    result = {}
    for embed_type in ["text", "code"]:
        key = f"embeddings_{embed_type}"
        result[embed_type] = task_routing.get(key, defaults[embed_type])
    
    return result


@config_router.put("/embeddings")
async def update_embedding_config(payload: DualEmbeddingConfig):
    """Update dual embedding model configuration."""
    loader = _get_loader()
    profiles = loader.load_namespace("profiles")
    task_routing = profiles.get("task_routing", {})
    
    if payload.text:
        task_routing["embeddings_text"] = {
            "model": payload.text.model,
            "provider": payload.text.provider,
            "dim": payload.text.dim
        }
    
    if payload.code:
        task_routing["embeddings_code"] = {
            "model": payload.code.model,
            "provider": payload.code.provider,
            "dim": payload.code.dim
        }
    
    profiles["task_routing"] = task_routing
    loader.save_namespace("profiles", profiles)
    
    return {
        "status": "success", 
        "embeddings_text": task_routing.get("embeddings_text"),
        "embeddings_code": task_routing.get("embeddings_code")
    }


# Provider Management

class ProviderCreate(BaseModel):
    name: str
    display_name: str
    provider_type: str  # openai_compatible, google_native, anthropic_native, openai_native
    api_base: Optional[str] = None
    api_key_env_var: Optional[str] = None
    is_local: Optional[bool] = False
    default_headers: Optional[Dict[str, str]] = None
    config: Optional[Dict[str, Any]] = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not re.match(r'^[a-z0-9_]+$', v):
            raise ValueError('Provider name must be lowercase alphanumeric with underscores')
        return v

    @field_validator('provider_type')
    @classmethod
    def validate_type(cls, v):
        valid_types = ['openai_compatible', 'google_native', 'anthropic_native', 'openai_native']
        if v not in valid_types:
            raise ValueError(f'Provider type must be one of: {", ".join(valid_types)}')
        return v


class ProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    api_base: Optional[str] = None
    api_key_env_var: Optional[str] = None
    is_local: Optional[bool] = None
    is_active: Optional[bool] = None
    default_headers: Optional[Dict[str, str]] = None
    config: Optional[Dict[str, Any]] = None


@config_router.get("/providers")
async def get_providers():
    """Get all configured providers."""
    loader = _get_loader()
    conn = loader._get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, name, display_name, provider_type, api_base, 
               api_key_env_var, is_local, is_active, default_headers, config
        FROM providers
        ORDER BY name
    """)
    
    providers = []
    for row in cur.fetchall():
        providers.append({
            "id": row[0],
            "name": row[1],
            "display_name": row[2],
            "provider_type": row[3],
            "api_base": row[4],
            "api_key_env_var": row[5],
            "is_local": row[6],
            "is_active": row[7],
            "default_headers": row[8] or {},
            "config": row[9] or {}
        })
    
    return providers


@config_router.post("/providers")
async def create_provider(payload: ProviderCreate):
    """Create a new provider."""
    loader = _get_loader()
    conn = loader._get_conn()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO providers (name, display_name, provider_type, api_base, api_key_env_var, is_local, default_headers, config)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            payload.name,
            payload.display_name,
            payload.provider_type,
            payload.api_base,
            payload.api_key_env_var,
            payload.is_local,
            payload.default_headers or {},
            payload.config or {}
        ))
        conn.commit()
        provider_id = cur.fetchone()[0]
        return {"status": "success", "id": provider_id, "name": payload.name}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@config_router.put("/providers/{provider_name}")
async def update_provider(provider_name: str, payload: ProviderUpdate):
    """Update a provider configuration."""
    loader = _get_loader()
    conn = loader._get_conn()
    cur = conn.cursor()
    
    # Build dynamic update
    updates = []
    values = []
    if payload.display_name is not None:
        updates.append("display_name = %s")
        values.append(payload.display_name)
    if payload.api_base is not None:
        updates.append("api_base = %s")
        values.append(payload.api_base)
    if payload.api_key_env_var is not None:
        updates.append("api_key_env_var = %s")
        values.append(payload.api_key_env_var)
    if payload.is_local is not None:
        updates.append("is_local = %s")
        values.append(payload.is_local)
    if payload.is_active is not None:
        updates.append("is_active = %s")
        values.append(payload.is_active)
    if payload.default_headers is not None:
        updates.append("default_headers = %s")
        values.append(payload.default_headers)
    if payload.config is not None:
        updates.append("config = %s")
        values.append(payload.config)
    
    if not updates:
        return {"status": "success", "message": "No changes"}
    
    values.append(provider_name)
    
    try:
        sql = f"UPDATE providers SET {', '.join(updates)}, updated_at = NOW() WHERE name = %s"  # nosec B608 - column names are from allowlisted keys, values are parameterized
        cur.execute(sql, values)
        conn.commit()
        
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
        
        # Refresh provider manager
        from src.shared.providers import get_provider_manager
        get_provider_manager().refresh()
        
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@config_router.delete("/providers/{provider_name}")
async def delete_provider(provider_name: str):
    """Delete a provider."""
    loader = _get_loader()
    conn = loader._get_conn()
    cur = conn.cursor()
    
    # Check if provider is being used
    cur.execute("SELECT COUNT(*) FROM app_config WHERE value::text LIKE %s", (f'%{provider_name}%',))
    count = cur.fetchone()[0]
    
    if count > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete provider '{provider_name}'. It is referenced in {count} configuration(s)."
        )
    
    cur.execute("DELETE FROM providers WHERE name = %s", (provider_name,))
    conn.commit()
    
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    
    from src.shared.providers import get_provider_manager
    get_provider_manager().refresh()
    
    return {"status": "success"}


@config_router.post("/reload")
async def reload_config():
    """
    Trigger config reload on all workers.
    
    Bumps the config version in the database, which signals workers
    to reload their cached configuration on the next activity.
    """
    loader = _get_loader()
    
    loader.invalidate_cache()
    loader.bump_config_version()
    
    from src.plugins.registry import registry
    registry.refresh_specializations()
    
    return {
        "status": "success",
        "message": "Config version bumped, workers will reload on next activity",
        "config_version": loader.get_config_version()
    }


@config_router.get("/version")
async def get_config_version():
    """Get current config version."""
    loader = _get_loader()
    return {
        "config_version": loader.get_config_version()
    }


class KnowledgeConfig(BaseModel):
    knowledge_collection: Optional[str] = None
    insights_collection: Optional[str] = None


@config_router.get("/knowledge")
async def get_knowledge_config():
    """Get knowledge base configuration."""
    loader = _get_loader()
    config = loader.load_namespace("knowledge") or {}
    return {
        "knowledge_collection": config.get("knowledge_collection", "knowledge_v1"),
        "insights_collection": config.get("insights_collection", "agent_insights_v4"),
    }


@config_router.put("/knowledge")
async def update_knowledge_config(payload: KnowledgeConfig):
    """Update knowledge base configuration."""
    loader = _get_loader()
    
    config = loader.load_namespace("knowledge") or {}
    
    if payload.knowledge_collection is not None:
        config["knowledge_collection"] = payload.knowledge_collection
    if payload.insights_collection is not None:
        config["insights_collection"] = payload.insights_collection
    
    loader.save_namespace("knowledge", config)
    loader.bump_config_version()
    
    return {
        "status": "success",
        "config": config,
        "note": "Workers will use new collection names after next activity (auto-reload)"
    }
