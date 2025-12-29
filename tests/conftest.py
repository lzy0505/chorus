"""Pytest fixtures for Claude Session Orchestrator tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

# Set up test config before importing any app modules
from config import Config, ServerConfig, DatabaseConfig, TmuxConfig, StatusPatterns, set_config

# Create test config with in-memory database
_test_project_root = Path(tempfile.mkdtemp())
_test_config = Config(
    server=ServerConfig(host="127.0.0.1", port=8000),
    database=DatabaseConfig(url="sqlite://"),
    tmux=TmuxConfig(session_prefix="test-claude", poll_interval=0.1),
    editor="vim",
    project_root=_test_project_root,
)
set_config(_test_config)


@pytest.fixture(name="engine")
def engine_fixture():
    """Create a test database engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="db")
def db_fixture(engine) -> Generator[Session, None, None]:
    """Create a test database session."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(engine) -> Generator[TestClient, None, None]:
    """Create a test client with overridden database."""
    from main import app
    from database import get_db

    def get_test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create a temporary project directory with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create sample markdown files
        (project_path / "README.md").write_text("# Test Project\n\nDescription here.")
        (project_path / "docs").mkdir()
        (project_path / "docs" / "guide.md").write_text(
            "# Guide\n\n## Section 1\n\nContent.\n\n## Section 2\n\nMore content."
        )

        yield project_path


@pytest.fixture
def sample_session_data() -> dict:
    """Sample session creation data."""
    return {
        "name": "test-session",
        "initial_prompt": None,
    }


@pytest.fixture
def sample_task_data() -> dict:
    """Sample task creation data."""
    return {
        "title": "Test Task",
        "description": "This is a test task description.",
        "priority": 5,
    }
