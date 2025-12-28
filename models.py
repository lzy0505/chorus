"""SQLModel definitions for Claude Session Orchestrator."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel, Relationship


class SessionStatus(str, Enum):
    """Session status enum."""
    idle = "idle"
    busy = "busy"
    waiting = "waiting"
    stopped = "stopped"


class TaskStatus(str, Enum):
    """Task status enum."""
    pending = "pending"
    assigned = "assigned"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    failed = "failed"


class DocumentCategory(str, Enum):
    """Document category enum."""
    instructions = "instructions"
    plans = "plans"
    communication = "communication"
    context = "context"
    general = "general"


class Session(SQLModel, table=True):
    """A tmux session running Claude Code."""
    id: str = Field(primary_key=True)  # format: claude-{name}
    task_id: Optional[int] = Field(default=None, foreign_key="task.id")
    status: SessionStatus = Field(default=SessionStatus.idle)
    last_output: str = Field(default="")
    permission_prompt: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(SQLModel, table=True):
    """A unit of work to be assigned to a session."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = Field(default="")
    priority: int = Field(default=0)
    status: TaskStatus = Field(default=TaskStatus.pending)
    session_id: Optional[str] = Field(default=None, foreign_key="session.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    result: Optional[str] = Field(default=None)


class Document(SQLModel, table=True):
    """A tracked markdown file in the project."""
    id: Optional[int] = Field(default=None, primary_key=True)
    path: str = Field(unique=True)
    category: DocumentCategory = Field(default=DocumentCategory.general)
    description: Optional[str] = Field(default=None)
    pinned: bool = Field(default=False)
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentReference(SQLModel, table=True):
    """A reference to specific lines in a document, linked to a task."""
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    task_id: Optional[int] = Field(default=None, foreign_key="task.id")
    start_line: int
    end_line: int
    note: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
