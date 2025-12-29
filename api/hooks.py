"""API endpoints for Claude Code hook events.

These endpoints receive events from Claude Code hooks and update task status
in real-time. The hook handler script POSTs to these endpoints when Claude
Code fires events like SessionStart, Stop, PermissionRequest, and SessionEnd.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus, ClaudeStatus

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


class HookEventPayload(BaseModel):
    """Payload received from Claude Code hooks.

    Claude Code sends this via stdin to hook commands, which then
    POST it to our API.
    """

    session_id: str
    hook_event_name: str
    transcript_path: Optional[str] = None
    cwd: Optional[str] = None


class HookResponse(BaseModel):
    """Response for hook events."""

    status: str
    task_id: Optional[int] = None
    message: Optional[str] = None


def find_task_by_session_id(db: Session, session_id: str) -> Optional[Task]:
    """Find a task by its Claude session ID."""
    statement = select(Task).where(Task.claude_session_id == session_id)
    return db.exec(statement).first()


def find_task_by_tmux_session(db: Session, cwd: str) -> Optional[Task]:
    """Find a task by checking if cwd matches a task's tmux session.

    When SessionStart fires, we don't have a session_id mapped yet,
    so we use the cwd (which should be the project root) to find
    a running task.
    """
    # Get all running tasks and check if any has a matching tmux session
    statement = select(Task).where(Task.status == TaskStatus.running)
    tasks = db.exec(statement).all()

    # For now, return the first running task
    # In a multi-project setup, we'd match cwd more precisely
    if tasks:
        return tasks[0]
    return None


def find_running_task(db: Session) -> Optional[Task]:
    """Find any running task (fallback when no session mapping exists)."""
    statement = select(Task).where(
        Task.status.in_([TaskStatus.running, TaskStatus.waiting])
    )
    return db.exec(statement).first()


@router.post("/sessionstart", response_model=HookResponse)
async def hook_session_start(
    payload: HookEventPayload,
    db: Session = Depends(get_db),
) -> HookResponse:
    """Handle Claude SessionStart hook event.

    Maps the Claude session_id to a task and sets status to idle.
    """
    # Try to find the task - first by cwd, then fallback to any running task
    task = None
    if payload.cwd:
        task = find_task_by_tmux_session(db, payload.cwd)

    if not task:
        task = find_running_task(db)

    if not task:
        return HookResponse(
            status="ignored",
            message="No running task found to map session to",
        )

    # Map session to task
    task.claude_session_id = payload.session_id
    task.claude_status = ClaudeStatus.idle

    db.add(task)
    db.commit()
    db.refresh(task)

    # TODO: Emit SSE event for claude_status change

    return HookResponse(
        status="ok",
        task_id=task.id,
        message=f"Mapped session {payload.session_id} to task {task.id}",
    )


@router.post("/stop", response_model=HookResponse)
async def hook_stop(
    payload: HookEventPayload,
    db: Session = Depends(get_db),
) -> HookResponse:
    """Handle Claude Stop hook event.

    Claude finished responding - set status to idle.
    """
    task = find_task_by_session_id(db, payload.session_id)

    if not task:
        return HookResponse(
            status="ignored",
            message=f"No task found for session {payload.session_id}",
        )

    # Update status to idle (finished responding)
    task.claude_status = ClaudeStatus.idle

    # If task was waiting for permission and we got a stop, reset to running
    if task.status == TaskStatus.waiting:
        task.status = TaskStatus.running
        task.permission_prompt = None

    db.add(task)
    db.commit()
    db.refresh(task)

    # TODO: Emit SSE event for claude_status change

    return HookResponse(
        status="ok",
        task_id=task.id,
        message=f"Task {task.id} Claude status set to idle",
    )


@router.post("/permissionrequest", response_model=HookResponse)
async def hook_permission_request(
    payload: HookEventPayload,
    db: Session = Depends(get_db),
) -> HookResponse:
    """Handle Claude PermissionRequest hook event.

    Claude is waiting for permission - update task status.
    """
    task = find_task_by_session_id(db, payload.session_id)

    if not task:
        return HookResponse(
            status="ignored",
            message=f"No task found for session {payload.session_id}",
        )

    # Update both Claude status and task status
    task.claude_status = ClaudeStatus.waiting
    task.status = TaskStatus.waiting

    # TODO: Extract permission prompt from transcript_path
    # For now, set a generic message
    task.permission_prompt = "Claude is waiting for permission"

    db.add(task)
    db.commit()
    db.refresh(task)

    # TODO: Emit SSE event for task_status change
    # TODO: Send desktop notification

    return HookResponse(
        status="ok",
        task_id=task.id,
        message=f"Task {task.id} waiting for permission",
    )


@router.post("/sessionend", response_model=HookResponse)
async def hook_session_end(
    payload: HookEventPayload,
    db: Session = Depends(get_db),
) -> HookResponse:
    """Handle Claude SessionEnd hook event.

    Claude session ended - clear session mapping and set status to stopped.
    """
    task = find_task_by_session_id(db, payload.session_id)

    if not task:
        return HookResponse(
            status="ignored",
            message=f"No task found for session {payload.session_id}",
        )

    # Clear session and set status to stopped
    task.claude_session_id = None
    task.claude_status = ClaudeStatus.stopped

    db.add(task)
    db.commit()
    db.refresh(task)

    # TODO: Emit SSE event for claude_status change

    return HookResponse(
        status="ok",
        task_id=task.id,
        message=f"Task {task.id} Claude session ended",
    )


@router.post("/notification", response_model=HookResponse)
async def hook_notification(
    payload: HookEventPayload,
    db: Session = Depends(get_db),
) -> HookResponse:
    """Handle Claude Notification hook event.

    This is fired for various notifications including idle prompts.
    For now, we treat it as confirmation that Claude is idle.
    """
    task = find_task_by_session_id(db, payload.session_id)

    if not task:
        return HookResponse(
            status="ignored",
            message=f"No task found for session {payload.session_id}",
        )

    # Notifications typically mean Claude is idle/waiting for input
    if task.claude_status != ClaudeStatus.waiting:
        task.claude_status = ClaudeStatus.idle

    db.add(task)
    db.commit()
    db.refresh(task)

    return HookResponse(
        status="ok",
        task_id=task.id,
        message=f"Task {task.id} notification received",
    )
