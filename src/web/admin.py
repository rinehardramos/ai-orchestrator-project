from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from src.web.api.tools import tools_router
from src.web.api.config import config_router
from src.web.api.status import status_router

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def create_admin_router() -> APIRouter:
    router = APIRouter()
    
    router.include_router(tools_router)
    router.include_router(config_router)
    router.include_router(status_router)
    
    @router.get("/ui/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})
    
    @router.get("/ui/tools", response_class=HTMLResponse)
    async def tools_list(request: Request):
        return templates.TemplateResponse("tools/list.html", {"request": request})
    
    @router.get("/ui/tools/new", response_class=HTMLResponse)
    async def tool_new(request: Request):
        return templates.TemplateResponse("tools/form.html", {"request": request, "tool": None})
    
    @router.get("/ui/tools/{name}", response_class=HTMLResponse)
    async def tool_edit(request: Request, name: str):
        return templates.TemplateResponse("tools/form.html", {"request": request, "tool_name": name})
    
    @router.get("/ui/models", response_class=HTMLResponse)
    async def models_page(request: Request):
        return templates.TemplateResponse("models/routing.html", {"request": request})
    
    @router.get("/ui/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse("settings/general.html", {"request": request})
    
    return router