"""Entry point for Chorus - Task-centric Claude orchestration."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from config import HOST, PORT
from database import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="Chorus",
    description="Task-centric orchestration for multiple Claude Code sessions",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Dashboard home page."""
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# API routers
from api.hooks import router as hooks_router
from api.tasks import router as tasks_router
from api.dashboard import router as dashboard_router
from api.events import router as events_router

app.include_router(hooks_router)
app.include_router(tasks_router)
app.include_router(dashboard_router)
app.include_router(events_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
