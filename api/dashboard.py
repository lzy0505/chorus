"""Dashboard routes for htmx partials.

These endpoints return HTML fragments for htmx to swap into the page.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus
from services.tmux import TmuxService, SessionNotFoundError

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


def _render_task_with_oob(request: Request, task: Task) -> HTMLResponse:
    """Render task detail with out-of-band task list item update."""
    # Check if tmux session exists for running/waiting tasks
    tmux_session_exists = False
    if task.status in (TaskStatus.running, TaskStatus.waiting):
        tmux = TmuxService()
        tmux_session_exists = tmux.session_exists(task.id)

    detail_html = templates.get_template("partials/task_detail.html").render(
        request=request, task=task, tmux_session_exists=tmux_session_exists
    )
    item_html = templates.get_template("partials/task_item.html").render(
        request=request, task=task
    )
    # Add hx-swap-oob to the task item for out-of-band swap
    oob_item = item_html.replace(
        f'id="task-{task.id}"',
        f'id="task-{task.id}" hx-swap-oob="true"'
    )
    return HTMLResponse(detail_html + oob_item)


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


@router.post("/tasks", response_class=HTMLResponse)
async def create_task(
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a task from form data and return task item HTML."""
    form = await request.form()
    title = form.get("title", "").strip()

    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    task = Task(title=title)
    db.add(task)
    db.commit()
    db.refresh(task)

    return templates.TemplateResponse(
        request, "partials/task_item.html", {"task": task}
    )


@router.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a task and return HTML to clear task item and detail panel."""
    from api.tasks import delete_task as api_delete_task

    try:
        await api_delete_task(task_id, db)
    except HTTPException:
        raise

    # Return empty content for the task item (removes it) plus OOB to clear detail
    empty_detail = '''<div class="panel-header" hx-swap-oob="innerHTML:#task-detail">Task Detail</div>
<p class="muted" hx-swap-oob="true" id="task-detail-placeholder">Select a task to view details</p>'''
    return HTMLResponse(empty_detail)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def get_task_detail(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Get task detail as HTML partial with OOB task list update."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Return detail with OOB swap for task list item
    return _render_task_with_oob(request, task)


@router.get("/tasks/{task_id}/output", response_class=HTMLResponse)
async def get_task_output(
    task_id: UUID,
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
    task_id: UUID,
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


@router.post("/tasks/{task_id}/start", response_class=HTMLResponse)
async def start_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Start a task and return updated task detail HTML + OOB task item."""
    from api.tasks import start_task as api_start_task, TaskStartRequest

    # Parse form data to get initial_prompt if provided
    form_data = await request.form()
    initial_prompt = form_data.get("initial_prompt", "").strip() or None

    # Call the API function to do the actual work
    try:
        await api_start_task(task_id, TaskStartRequest(initial_prompt=initial_prompt), db)
    except HTTPException:
        raise

    # Refresh task and return HTML with OOB swap for task list item
    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/restart-claude", response_class=HTMLResponse)
async def restart_claude(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Restart Claude and return updated task detail HTML + OOB task item."""
    from api.tasks import restart_claude as api_restart_claude

    try:
        await api_restart_claude(task_id, db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/complete", response_class=HTMLResponse)
async def complete_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Complete a task and return updated task detail HTML + OOB task item."""
    from api.tasks import complete_task as api_complete_task, TaskCompleteRequest

    try:
        await api_complete_task(task_id, TaskCompleteRequest(), db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/fail", response_class=HTMLResponse)
async def fail_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Fail a task and return updated task detail HTML + OOB task item."""
    from api.tasks import fail_task as api_fail_task, TaskFailRequest

    try:
        await api_fail_task(task_id, TaskFailRequest(), db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/respond", response_class=HTMLResponse)
async def respond_to_permission(
    request: Request,
    task_id: UUID,
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

    return _render_task_with_oob(request, task)
