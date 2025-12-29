"""Entry point for Chorus - Task-centric Claude orchestration."""

import argparse
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from config import load_config, set_config, get_config
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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="chorus",
        description="Task-centric orchestration for multiple Claude Code sessions",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to TOML configuration file (e.g., chorus.toml)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)
    set_config(config)

    uvicorn.run(
        "main:app",
        host=config.server.host,
        port=config.server.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
