"""Dashboard routes for htmx partials.

These endpoints return HTML fragments for htmx to swap into the page.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus
from services.tmux import TmuxService, SessionNotFoundError

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


@router.get("/tasks", response_class=HTMLResponse)
async def get_task_list(
    request: Request,
    status: Optional[TaskStatus] = None,
    db: Session = Depends(get_db),
):
    """Get task list as HTML partial."""
    statement = select(Task)
    if status:
        statement = statement.where(Task.status == status)
    statement = statement.order_by(Task.priority.desc(), Task.created_at.desc())
    tasks = list(db.exec(statement).all())

    return templates.TemplateResponse(
        request, "partials/task_list.html", {"tasks": tasks}
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def get_task_detail(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db),
):
    """Get task detail as HTML partial."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return templates.TemplateResponse(
        request, "partials/task_detail.html", {"task": task}
    )


@router.get("/tasks/{task_id}/output", response_class=HTMLResponse)
async def get_task_output(
    task_id: int,
    db: Session = Depends(get_db),
):
    """Get terminal output as HTML."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        return HTMLResponse("<span class='muted'>No active session</span>")

    tmux = TmuxService()
    try:
        output = tmux.capture_output(task_id, lines=50)
        # Escape HTML and preserve whitespace
        import html
        escaped = html.escape(output)
        return HTMLResponse(f"<code>{escaped}</code>")
    except SessionNotFoundError:
        return HTMLResponse("<span class='muted'>Session not found</span>")


@router.post("/tasks/{task_id}/send", response_class=HTMLResponse)
async def send_message(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db),
):
    """Send a message to Claude and return updated output."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    form = await request.form()
    message = form.get("message", "")

    if not message:
        return await get_task_output(task_id, db)

    tmux = TmuxService()
    try:
        tmux.send_keys(task_id, message)
    except SessionNotFoundError:
        return HTMLResponse("<span class='error'>Session not found</span>")

    # Return current output (will update via polling)
    return await get_task_output(task_id, db)


@router.post("/tasks/{task_id}/respond", response_class=HTMLResponse)
async def respond_to_permission(
    request: Request,
    task_id: int,
    confirm: bool = True,
    db: Session = Depends(get_db),
):
    """Respond to permission prompt and return updated detail."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    tmux = TmuxService()
    try:
        tmux.send_confirmation(task_id, confirm)
    except SessionNotFoundError:
        pass

    task.permission_prompt = None
    db.add(task)
    db.commit()
    db.refresh(task)

    return templates.TemplateResponse(
        request, "partials/task_detail.html", {"task": task}
    )
