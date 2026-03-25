"""
Tools API - Database-only configuration.

NO YAML fallback.
"""

import os
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

tools_router = APIRouter(prefix="/api")


async def invalidate_tool_cache(tool_name: str = None) -> None:
    pass


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def get_db_info():
    return get_db_url(), ""


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


class CredentialDelete(BaseModel):
    key: str


def mask_credentials(credentials: dict) -> dict:
    if not credentials:
        return {}
    return {k: "••••••" for k in credentials.keys()}


async def _get_all_db(db_url: str):
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch("SELECT * FROM tools ORDER BY name")
        result = []
        for row in rows:
            name = row["name"]
            config_rows = await conn.fetch(
                "SELECT key, value FROM tool_configs WHERE tool_name=$1", name
            )
            config = {r["key"]: r["value"] for r in config_rows}
            cred_rows = await conn.fetch(
                "SELECT key FROM credentials WHERE tool_name=$1", name
            )
            creds = {r["key"]: "••••••" for r in cred_rows}
            result.append({
                "name": name,
                "type": row["type"],
                "module": row["module"],
                "enabled": row["enabled"],
                "listen": row["listen"],
                "node": row["node"],
                "description": row["description"],
                "config": config,
                "credentials": creds,
                "has_credentials": len(creds) > 0
            })
        return result
    finally:
        await conn.close()


async def _get_tool_db(db_url: str, name: str):
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow("SELECT * FROM tools WHERE name=$1", name)
        if not row:
            return None
        config_rows = await conn.fetch(
            "SELECT key, value FROM tool_configs WHERE tool_name=$1", name
        )
        config = {r["key"]: r["value"] for r in config_rows}
        cred_rows = await conn.fetch(
            "SELECT key FROM credentials WHERE tool_name=$1", name
        )
        creds = {r["key"]: "••••••" for r in cred_rows}
        return {
            "name": name,
            "type": row["type"],
            "module": row["module"],
            "enabled": row["enabled"],
            "listen": row["listen"],
            "node": row["node"],
            "description": row["description"],
            "config": config,
            "credentials": creds,
            "has_credentials": len(creds) > 0
        }
    finally:
        await conn.close()


@tools_router.get("/tools")
async def list_tools() -> List[dict]:
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        return await _get_all_db(db_url)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


@tools_router.get("/tools/{name}")
async def get_tool(name: str):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        tool = await _get_tool_db(db_url, name)
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        return tool
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


@tools_router.post("/tools")
async def create_tool(tool: ToolCreate, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                "INSERT INTO tools (name, type, module, enabled, listen, node, description) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                "ON CONFLICT (name) DO UPDATE SET "
                    "type = EXCLUDED.type, "
                    "module = EXCLUDED.module, "
                    "enabled = EXCLUDED.enabled, "
                    "listen = EXCLUDED.listen, "
                    "node = EXCLUDED.node, "
                    "description = EXCLUDED.description, "
                    "updated_at = now()",
                tool.name, tool.type, tool.module, tool.enabled,
                tool.listen, tool.node, tool.description
            )
            for k, v in tool.config.items():
                await conn.execute(
                    "INSERT INTO tool_configs (tool_name, key, value) VALUES ($1, $2, $3) "
                    "ON CONFLICT (tool_name, key) DO UPDATE SET value = EXCLUDED.value",
                    tool.name, k, str(v)
                )
            background_tasks.add_task(invalidate_tool_cache, tool.name)
            return {"status": "success", "name": tool.name}
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")


@tools_router.put("/tools/{name}")
async def update_tool(name: str, payload: ToolUpdate, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
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
                    await conn.execute(
                        "INSERT INTO tool_configs (tool_name, key, value) VALUES ($1, $2, $3) "
                        "ON CONFLICT (tool_name, key) DO UPDATE SET value = EXCLUDED.value",
                        name, k, str(v)
                    )
            
            if payload.credentials is not None and len(payload.credentials) > 0:
                secret_key = os.environ.get("CONFIG_SECRET_KEY", "")
                if not secret_key:
                    import base64
                    import os as _os
                    secret_key = base64.b64encode(_os.urandom(32)).decode()
                    os.environ["CONFIG_SECRET_KEY"] = secret_key
                
                from src.plugins.loader import encrypt_credential
                for k, v in payload.credentials.items():
                    enc = encrypt_credential(str(v), secret_key)
                    if enc:
                        await conn.execute(
                            "DELETE FROM credentials WHERE tool_name=$1 AND key=$2",
                            name, k
                        )
                        await conn.execute(
                            "INSERT INTO credentials (tool_name, key, value) VALUES ($1, $2, $3)",
                            name, k, enc
                        )
            
            background_tasks.add_task(invalidate_tool_cache, name)
            return {"status": "success"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")


@tools_router.delete("/tools/{name}")
async def delete_tool(name: str, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            res = await conn.execute("DELETE FROM tools WHERE name=$1", name)
            if res == "DELETE 0":
                raise HTTPException(status_code=404, detail="Tool not found")
            background_tasks.add_task(invalidate_tool_cache, name)
            return {"status": "success"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")


@tools_router.patch("/tools/{name}/enable")
async def enable_tool(name: str, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            res = await conn.execute(
                "UPDATE tools SET enabled=true WHERE name=$1", name
            )
            if res == "UPDATE 0":
                raise HTTPException(status_code=404, detail="Tool not found")
            background_tasks.add_task(invalidate_tool_cache, name)
            return {"status": "success", "enabled": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")


@tools_router.patch("/tools/{name}/disable")
async def disable_tool(name: str, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            res = await conn.execute(
                "UPDATE tools SET enabled=false WHERE name=$1", name
            )
            if res == "UPDATE 0":
                raise HTTPException(status_code=404, detail="Tool not found")
            background_tasks.add_task(invalidate_tool_cache, name)
            return {"status": "success", "enabled": False}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")


@tools_router.delete("/tools/{name}/credentials/{key}")
async def delete_credential(name: str, key: str, background_tasks: BackgroundTasks):
    db_url = get_db_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow("SELECT 1 FROM tools WHERE name=$1", name)
            if not row:
                raise HTTPException(status_code=404, detail="Tool not found")
            
            res = await conn.execute(
                "DELETE FROM credentials WHERE tool_name=$1 AND key=$2",
                name, key
            )
            background_tasks.add_task(invalidate_tool_cache, name)
            return {"status": "success", "deleted_key": key}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
        finally:
            await conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection error: {str(e)}")
