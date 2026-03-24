import os
import yaml
import json
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from src.plugins.loader import _load_bootstrap, invalidate_tool_cache, encrypt_credential

tools_router = APIRouter(prefix="/api")
TOOLS_YAML_PATH = "config/tools.yaml"
BOOTSTRAP_PATH = "config/bootstrap.yaml"

class ToolCreate(BaseModel):
    name: str
    type: str
    module: str
    enabled: bool = False
    listen: bool = False
    node: str = "both"
    description: Optional[str] = ""
    config: dict = {}
    credentials: dict = {}

class ToolUpdate(BaseModel):
    config: Optional[dict] = None
    credentials: Optional[dict] = None

def get_db_info():
    bootstrap = _load_bootstrap(BOOTSTRAP_PATH)
    return bootstrap.get("database_url"), bootstrap.get("secret_key")

def mask_credentials(credentials: dict) -> dict:
    if not credentials: return {}
    return {k: "••••••" for k in credentials.keys()}

def load_yaml():
    if not os.path.exists(TOOLS_YAML_PATH):
        return {"tools": {}}
    with open(TOOLS_YAML_PATH, "r") as f:
        return yaml.safe_load(f) or {"tools": {}}

def save_yaml(data: dict):
    # Atomic write
    tmp_path = TOOLS_YAML_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp_path, TOOLS_YAML_PATH)

async def _get_all_db(db_url: str):
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch("SELECT * FROM tools ORDER BY name")
        result = {}
        for row in rows:
            name = row["name"]
            config_rows = await conn.fetch("SELECT key, value FROM tool_configs WHERE tool_name=$1", name)
            conf = {r["key"]: r["value"] for r in config_rows}
            cred_rows = await conn.fetch("SELECT key FROM credentials WHERE tool_name=$1", name)
            creds = {r["key"]: "••••••" for r in cred_rows}

            result[name] = {
                "name": name,
                "type": row["type"],
                "module": row["module"],
                "enabled": row["enabled"],
                "listen": row["listen"],
                "node": row["node"],
                "description": row["description"],
                "config": conf,
                "credentials": creds
            }
        return list(result.values())
    finally:
        await conn.close()

async def _get_tool_db(db_url: str, name: str):
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow("SELECT * FROM tools WHERE name=$1", name)
        if not row: return None
        config_rows = await conn.fetch("SELECT key, value FROM tool_configs WHERE tool_name=$1", name)
        conf = {r["key"]: r["value"] for r in config_rows}
        cred_rows = await conn.fetch("SELECT key FROM credentials WHERE tool_name=$1", name)
        creds = {r["key"]: "••••••" for r in cred_rows}

        return {
            "name": name,
            "type": row["type"],
            "module": row["module"],
            "enabled": row["enabled"],
            "listen": row["listen"],
            "node": row["node"],
            "description": row["description"],
            "config": conf,
            "credentials": creds
        }
    finally:
        await conn.close()

@tools_router.get("/tools")
async def list_tools() -> List[dict]:
    db_url, secret_key = get_db_info()
    if db_url:
        try:
            return await _get_all_db(db_url)
        except Exception as e:
            # Fall back to YAML logic
            pass
    
    # YAML logic
    data = load_yaml()
    tools = data.get("tools", {})
    res = []
    for k, v in tools.items():
        if isinstance(v, dict) and "module" in v:
            t = dict(v)
            t["name"] = k
            if "credentials" in t:
                t["credentials"] = mask_credentials(t["credentials"])
            res.append(t)
    return res

@tools_router.get("/tools/{name}")
async def get_tool(name: str):
    db_url, secret_key = get_db_info()
    if db_url:
        try:
            t = await _get_tool_db(db_url, name)
            if t: return t
            raise HTTPException(status_code=404, detail="Tool not found")
        except HTTPException:
            raise
        except Exception:
            pass

    data = load_yaml()
    tools = data.get("tools", {})
    if name not in tools:
        raise HTTPException(status_code=404, detail="Tool not found")
    t = dict(tools[name])
    t["name"] = name
    if "credentials" in t:
        t["credentials"] = mask_credentials(t["credentials"])
    return t

@tools_router.post("/tools")
async def create_tool(tool: ToolCreate, background_tasks: BackgroundTasks):
    db_url, secret_key = get_db_info()
    if db_url and secret_key:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url)
            try:
                # INSERT into logic
                await conn.execute(
                    "INSERT INTO tools (name, type, module, enabled, listen, node, description) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    tool.name, tool.type, tool.module, tool.enabled, tool.listen, tool.node, tool.description
                )
                for k, v in tool.config.items():
                    await conn.execute("INSERT INTO tool_configs (tool_name, key, value) VALUES ($1, $2, $3)", tool.name, k, str(v))
                for k, v in tool.credentials.items():
                    enc = encrypt_credential(str(v), secret_key)
                    await conn.execute("INSERT INTO credentials (tool_name, key, value) VALUES ($1, $2, $3)", tool.name, k, enc)
                background_tasks.add_task(invalidate_tool_cache, tool.name)
                return {"status": "success", "name": tool.name}
            except asyncpg.exceptions.UniqueViolationError:
                raise HTTPException(status_code=400, detail="Tool already exists")
            finally:
                await conn.close()
        except HTTPException:
            raise
        except Exception as e:
            # Fall back to yaml
            pass

    # YAML fallback
    data = load_yaml()
    if "tools" not in data: data["tools"] = {}
    if tool.name in data["tools"]:
        raise HTTPException(status_code=400, detail="Tool already exists")
    data["tools"][tool.name] = {
        "type": tool.type,
        "module": tool.module,
        "enabled": tool.enabled,
        "listen": tool.listen,
        "node": tool.node,
        "description": tool.description,
        "config": tool.config,
        "credentials": tool.credentials
    }
    save_yaml(data)
    background_tasks.add_task(invalidate_tool_cache, tool.name)
    return {"status": "success", "name": tool.name}

@tools_router.put("/tools/{name}")
async def update_tool(name: str, payload: ToolUpdate, background_tasks: BackgroundTasks):
    db_url, secret_key = get_db_info()
    if db_url and secret_key:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url)
            try:
                row = await conn.fetchrow("SELECT 1 FROM tools WHERE name=$1", name)
                if not row:
                    raise HTTPException(status_code=404, detail="Tool not found")
                
                if payload.config is not None:
                    await conn.execute("DELETE FROM tool_configs WHERE tool_name=$1", name)
                    for k, v in payload.config.items():
                        await conn.execute("INSERT INTO tool_configs (tool_name, key, value) VALUES ($1, $2, $3)", name, k, str(v))
                        
                if payload.credentials is not None:
                    await conn.execute("DELETE FROM credentials WHERE tool_name=$1", name)
                    for k, v in payload.credentials.items():
                        enc = encrypt_credential(str(v), secret_key)
                        await conn.execute("INSERT INTO credentials (tool_name, key, value) VALUES ($1, $2, $3)", name, k, enc)
                
                background_tasks.add_task(invalidate_tool_cache, name)
                return {"status": "success"}
            finally:
                await conn.close()
        except HTTPException:
            raise
        except Exception:
            pass
            
    # YAML fallback
    data = load_yaml()
    if "tools" not in data or name not in data["tools"]:
        raise HTTPException(status_code=404, detail="Tool not found")
        
    if payload.config is not None:
        data["tools"][name]["config"] = payload.config
    if payload.credentials is not None:
        data["tools"][name]["credentials"] = payload.credentials
        
    save_yaml(data)
    background_tasks.add_task(invalidate_tool_cache, name)
    return {"status": "success"}

@tools_router.delete("/tools/{name}")
async def delete_tool(name: str, background_tasks: BackgroundTasks):
    db_url, secret_key = get_db_info()
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url)
            try:
                res = await conn.execute("DELETE FROM tools WHERE name=$1", name)
                if res == "DELETE 0":
                    raise HTTPException(status_code=404, detail="Tool not found")
                background_tasks.add_task(invalidate_tool_cache, name)
                return {"status": "success"}
            finally:
                await conn.close()
        except HTTPException:
            raise
        except Exception:
            pass
            
    # YAML fallback
    data = load_yaml()
    if "tools" not in data or name not in data["tools"]:
        raise HTTPException(status_code=404, detail="Tool not found")
    del data["tools"][name]
    save_yaml(data)
    background_tasks.add_task(invalidate_tool_cache, name)
    return {"status": "success"}

@tools_router.patch("/tools/{name}/enable")
async def enable_tool(name: str, background_tasks: BackgroundTasks):
    db_url, secret_key = get_db_info()
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url)
            try:
                res = await conn.execute("UPDATE tools SET enabled=true WHERE name=$1", name)
                if res == "UPDATE 0":
                    raise HTTPException(status_code=404, detail="Tool not found")
                background_tasks.add_task(invalidate_tool_cache, name)
                return {"status": "success", "enabled": True}
            finally:
                await conn.close()
        except HTTPException:
            raise
        except Exception:
            pass
            
    data = load_yaml()
    if "tools" not in data or name not in data["tools"]:
        raise HTTPException(status_code=404, detail="Tool not found")
    data["tools"][name]["enabled"] = True
    save_yaml(data)
    background_tasks.add_task(invalidate_tool_cache, name)
    return {"status": "success", "enabled": True}

@tools_router.patch("/tools/{name}/disable")
async def disable_tool(name: str, background_tasks: BackgroundTasks):
    db_url, secret_key = get_db_info()
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url)
            try:
                res = await conn.execute("UPDATE tools SET enabled=false WHERE name=$1", name)
                if res == "UPDATE 0":
                    raise HTTPException(status_code=404, detail="Tool not found")
                background_tasks.add_task(invalidate_tool_cache, name)
                return {"status": "success", "enabled": False}
            finally:
                await conn.close()
        except HTTPException:
            raise
        except Exception:
            pass
            
    data = load_yaml()
    if "tools" not in data or name not in data["tools"]:
        raise HTTPException(status_code=404, detail="Tool not found")
    data["tools"][name]["enabled"] = False
    save_yaml(data)
    background_tasks.add_task(invalidate_tool_cache, name)
    return {"status": "success", "enabled": False}
