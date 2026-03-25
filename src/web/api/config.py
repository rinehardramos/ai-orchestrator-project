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
    def validate_id(cls, v):
        if not re.match(r'^[a-z0-9-]+/[a-z0-9-_.]+$', v):
            raise ValueError('Model ID must be in format: provider/model-name (lowercase, alphanumeric, hyphens, underscores)')
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
