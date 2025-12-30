"""Entry point for Chorus - Task-centric Claude orchestration."""

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from config import load_config, set_config, get_config
from database import create_db_and_tables
from services.error_handler import (
    ServiceError,
    RecoverableError,
    UnrecoverableError,
    log_service_error,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _ensure_config():
    """Ensure config is loaded, using environment variables if needed.

    This is needed because uvicorn with reload=True spawns a new process
    that reimports the module without running main().
    """
    try:
        get_config()
    except RuntimeError:
        # Config not set - load from environment variables
        config_path = os.environ.get("CHORUS_CONFIG_PATH")
        project_path = os.environ.get("CHORUS_PROJECT_PATH")
        if config_path and project_path:
            config = load_config(config_path, project_root=project_path)
            set_config(config)
        else:
            raise RuntimeError(
                "Configuration not initialized and CHORUS_CONFIG_PATH / "
                "CHORUS_PROJECT_PATH environment variables not set."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    _ensure_config()
    create_db_and_tables()

    # Start status poller in hybrid mode (if enabled)
    # Hooks provide fast updates, poller acts as safety net
    config = get_config()
    if config.status_polling.enabled:
        from services.status_poller import get_status_poller
        poller = get_status_poller(
            interval=config.status_polling.interval,
            frozen_threshold=config.status_polling.frozen_threshold
        )
        poller.start()
        logger.info(f"Status poller started in hybrid mode (interval: {config.status_polling.interval}s, frozen_threshold: {config.status_polling.frozen_threshold}s)")
    else:
        poller = None
        logger.info("Status polling disabled in configuration")

    yield

    # Shutdown
    if poller is not None:
        await poller.stop()
        stats = poller.get_stats()
        logger.info(f"Status poller stopped. Corrections made: {stats['correction_count']}")
    pass


app = FastAPI(
    title="Chorus",
    description="Task-centric orchestration for multiple Claude Code sessions",
    version="0.1.0",
    lifespan=lifespan,
)


# Exception handlers
@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    """Handle service errors (tmux, gitbutler, etc)."""
    status_code = 500
    error_type = "service_error"

    if isinstance(exc, RecoverableError):
        status_code = 409  # Conflict - can be retried
        error_type = "recoverable_error"
    elif isinstance(exc, UnrecoverableError):
        status_code = 500
        error_type = "unrecoverable_error"

    logger.error(f"{error_type}: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_type,
            "message": str(exc),
            "detail": "Check logs for more information",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed messages."""
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Invalid request data",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unexpected errors."""
    logger.exception(f"Unexpected error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
            "detail": str(exc) if os.environ.get("DEBUG") else "Check logs",
        },
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
    parser.add_argument(
        "project",
        type=Path,
        help="Absolute path to the project directory to manage",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    if not args.project.is_absolute():
        print(f"Error: Project path must be absolute: {args.project}", file=sys.stderr)
        sys.exit(1)

    if not args.project.is_dir():
        print(f"Error: Project path is not a directory: {args.project}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config, project_root=args.project)
    set_config(config)

    # Set environment variables for uvicorn reload subprocess
    os.environ["CHORUS_CONFIG_PATH"] = str(args.config.resolve())
    os.environ["CHORUS_PROJECT_PATH"] = str(args.project)

    uvicorn.run(
        "main:app",
        host=config.server.host,
        port=config.server.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
