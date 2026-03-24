import os
import yaml
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

config_router = APIRouter(prefix="/api/config")

PROFILES_YAML = "config/profiles.yaml"
SETTINGS_YAML = "config/settings.yaml"
JOBS_YAML = "config/jobs.yaml"
CLUSTER_YAML = "config/cluster_nodes.yaml"


def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: str, data: dict):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp_path, path)


class RoutingUpdate(BaseModel):
    routing: Dict[str, Any]


class SpecializationsUpdate(BaseModel):
    specializations: Dict[str, Any]


class AgentDefaultsUpdate(BaseModel):
    agent_defaults: Dict[str, Any]


class InfrastructureUpdate(BaseModel):
    infrastructure: Dict[str, Any]


class ClusterUpdate(BaseModel):
    nodes: List[Dict[str, Any]]


@config_router.get("/routing")
async def get_routing():
    data = load_yaml(PROFILES_YAML)
    return data.get("task_routing", {})


@config_router.put("/routing")
async def update_routing(payload: RoutingUpdate):
    data = load_yaml(PROFILES_YAML)
    data["task_routing"] = payload.routing
    save_yaml(PROFILES_YAML, data)
    return {"status": "success"}


@config_router.get("/models")
async def get_models():
    data = load_yaml(PROFILES_YAML)
    return data.get("models", [])


@config_router.get("/specializations")
async def get_specializations():
    data = load_yaml(PROFILES_YAML)
    return data.get("specializations", {})


@config_router.put("/specializations")
async def update_specializations(payload: SpecializationsUpdate):
    data = load_yaml(PROFILES_YAML)
    data["specializations"] = payload.specializations
    save_yaml(PROFILES_YAML, data)
    return {"status": "success"}


@config_router.get("/agent-defaults")
async def get_agent_defaults():
    data = load_yaml(JOBS_YAML)
    return data.get("agent_defaults", {})


@config_router.put("/agent-defaults")
async def update_agent_defaults(payload: AgentDefaultsUpdate):
    data = load_yaml(JOBS_YAML)
    data["agent_defaults"] = payload.agent_defaults
    save_yaml(JOBS_YAML, data)
    return {"status": "success"}


@config_router.get("/infrastructure")
async def get_infrastructure():
    data = load_yaml(SETTINGS_YAML)
    return data


@config_router.put("/infrastructure")
async def update_infrastructure(payload: Dict[str, Any]):
    save_yaml(SETTINGS_YAML, payload)
    return {"status": "success"}


@config_router.get("/cluster")
async def get_cluster():
    data = load_yaml(CLUSTER_YAML)
    return data.get("nodes", [])


@config_router.put("/cluster")
async def update_cluster(payload: ClusterUpdate):
    data = load_yaml(CLUSTER_YAML)
    comments = None
    if "_comments" in data:
        comments = data["_comments"]
    data["nodes"] = payload.nodes
    if comments:
        data["_comments"] = comments
    save_yaml(CLUSTER_YAML, data)
    return {"status": "success"}
