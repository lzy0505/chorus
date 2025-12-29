"""Entry point for Claude Session Orchestrator."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import HOST, PORT
from database import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    # TODO: Start session monitor background task
    yield
    # Shutdown
    # TODO: Stop session monitor


app = FastAPI(
    title="Claude Session Orchestrator",
    description="Manage multiple Claude Code sessions for a single project",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def index():
    """Dashboard home page."""
    return {"message": "Claude Session Orchestrator", "status": "running"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# API routers
from api.hooks import router as hooks_router

app.include_router(hooks_router)

# TODO: Include remaining API routers
# from api import tasks, documents, events
# app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
# app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
# app.include_router(events.router, prefix="/api", tags=["events"])


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
