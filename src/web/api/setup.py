from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from src.config_db import get_loader

setup_router = APIRouter(prefix="/api/setup")

@setup_router.get("/status")
async def get_setup_status():
    loader = get_loader()
    return {"setup_complete": loader.validate_setup()}

@setup_router.post("/complete")
async def complete_setup():
    loader = get_loader()
    missing = loader.get_missing_config()
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing config: {missing}")
    
    loader.mark_setup_complete()
    return {"status": "success"}
