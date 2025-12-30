"""Task API endpoints for full task lifecycle management.

Tasks are the primary entity in Chorus. Each task:
- Runs in its own tmux process
- Has its own GitButler stack (virtual branch)
- Can have Claude restarted without losing context
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus, ClaudeStatus
from services.tmux import TmuxService, SessionExistsError, SessionNotFoundError
from services.gitbutler import GitButlerService, StackExistsError, GitButlerError
from services.hooks import HooksService
from services.context import write_task_context, cleanup_task_context, get_context_file

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# Request/Response models
class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: str
    description: str = ""
    priority: int = 0


class TaskUpdate(BaseModel):
    """Request body for updating a task."""

    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None


class TaskResponse(BaseModel):
    """Response model for task data."""

    id: int
    title: str
    description: str
    priority: int
    status: TaskStatus
    stack_name: Optional[str]
    tmux_session: Optional[str]
    claude_status: ClaudeStatus
    claude_restarts: int
    permission_prompt: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class TaskStartRequest(BaseModel):
    """Request body for starting a task."""

    initial_prompt: Optional[str] = None


class TaskSendRequest(BaseModel):
    """Request body for sending a message to Claude."""

    message: str


class TaskRespondRequest(BaseModel):
    """Request body for responding to a permission prompt."""

    confirm: bool


class TaskCompleteRequest(BaseModel):
    """Request body for completing a task."""

    result: Optional[str] = None


class TaskFailRequest(BaseModel):
    """Request body for failing a task."""

    reason: Optional[str] = None
    delete_stack: bool = False


class ActionResponse(BaseModel):
    """Response for action endpoints."""

    status: str
    message: str
    task_id: int


# Helper functions
def get_task_or_404(db: Session, task_id: int) -> Task:
    """Get a task by ID or raise 404."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def generate_stack_name(task: Task) -> str:
    """Generate a GitButler stack name for a task."""
    # Sanitize title for use in branch name
    safe_title = "".join(c if c.isalnum() else "-" for c in task.title.lower())
    safe_title = safe_title[:30].strip("-")  # Limit length
    return f"task-{task.id}-{safe_title}"


# CRUD Endpoints
@router.post("", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
) -> Task:
    """Create a new task.

    The task starts in 'pending' status. Use POST /api/tasks/{id}/start
    to create the GitButler stack and start Claude.
    """
    task = Task(
        title=task_data.title,
        description=task_data.description,
        priority=task_data.priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    db: Session = Depends(get_db),
) -> list[Task]:
    """List all tasks, optionally filtered by status."""
    statement = select(Task)
    if status:
        statement = statement.where(Task.status == status)
    statement = statement.order_by(Task.priority.desc(), Task.created_at.desc())
    return list(db.exec(statement).all())


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> Task:
    """Get a task by ID."""
    return get_task_or_404(db, task_id)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_data: TaskUpdate,
    db: Session = Depends(get_db),
) -> Task:
    """Update a task's title, description, or priority."""
    task = get_task_or_404(db, task_id)

    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description
    if task_data.priority is not None:
        task.priority = task_data.priority

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Delete a task.

    Only pending or failed tasks can be deleted. Running tasks must be
    completed or failed first.
    """
    task = get_task_or_404(db, task_id)

    if task.status in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete running task. Complete or fail it first.",
        )

    db.delete(task)
    db.commit()

    return ActionResponse(
        status="ok",
        message=f"Task {task_id} deleted",
        task_id=task_id,
    )


# Lifecycle Endpoints
@router.post("/{task_id}/start", response_model=ActionResponse)
async def start_task(
    task_id: int,
    request: TaskStartRequest = TaskStartRequest(),
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Start a task.

    This:
    1. Creates a GitButler stack for the task
    2. Creates a tmux session
    3. Sets up Claude Code hooks
    4. Launches Claude in the tmux session

    The task must be in 'pending' status.
    """
    task = get_task_or_404(db, task_id)

    if task.status != TaskStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only start pending tasks",
        )

    gitbutler = GitButlerService()
    tmux = TmuxService()
    hooks = HooksService()

    # 1. Create GitButler stack
    stack_name = generate_stack_name(task)
    try:
        stack = gitbutler.create_stack(stack_name)
        task.stack_name = stack.name
        task.stack_id = stack.cli_id
    except StackExistsError:
        # Stack already exists (maybe from a previous failed start)
        task.stack_name = stack_name
    except GitButlerError as e:
        raise HTTPException(status_code=500, detail=f"GitButler error: {e}")

    # 2. Create tmux session
    try:
        session_id = tmux.create_task_session(task_id)
        task.tmux_session = session_id
    except SessionExistsError:
        # Session already exists
        task.tmux_session = tmux.get_session_id(task_id)

    # 3. Set up hooks
    hooks.setup_hooks(task_id)

    # 4. Update task status
    task.status = TaskStatus.running
    task.claude_status = ClaudeStatus.starting
    task.started_at = datetime.now(timezone.utc)

    db.add(task)
    db.commit()
    db.refresh(task)

    # 5. Write task context to /tmp (not in project directory)
    context_file = write_task_context(task, user_prompt=request.initial_prompt)

    # 6. Start Claude in tmux with context injected via --append-system-prompt
    tmux.start_claude(task_id, context_file=context_file)

    return ActionResponse(
        status="ok",
        message=f"Task {task_id} started with stack '{task.stack_name}'",
        task_id=task_id,
    )


@router.post("/{task_id}/restart-claude", response_model=ActionResponse)
async def restart_claude(
    task_id: int,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Restart Claude in the task's tmux session.

    Use this when Claude hangs, crashes, or loses context.
    The tmux session and GitButler stack are preserved.
    """
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only restart running tasks",
        )

    tmux = TmuxService()

    # Get context file path (context was written when task started)
    context_file = get_context_file(task_id)

    try:
        tmux.restart_claude(task_id, context_file=context_file)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Tmux session for task {task_id} not found",
        )

    # Update task state
    task.claude_status = ClaudeStatus.starting
    task.claude_session_id = None  # Will be set by SessionStart hook
    task.claude_restarts += 1
    task.permission_prompt = None

    if task.status == TaskStatus.waiting:
        task.status = TaskStatus.running

    db.add(task)
    db.commit()

    return ActionResponse(
        status="ok",
        message=f"Claude restarted for task {task_id} (restart #{task.claude_restarts})",
        task_id=task_id,
    )


@router.post("/{task_id}/send", response_model=ActionResponse)
async def send_message(
    task_id: int,
    request: TaskSendRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Send a message to Claude in the task's tmux session."""
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, cannot send messages",
        )

    if task.claude_status != ClaudeStatus.idle:
        raise HTTPException(
            status_code=400,
            detail=f"Claude is {task.claude_status}, wait until idle",
        )

    tmux = TmuxService()

    try:
        tmux.send_keys(task_id, request.message)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Tmux session for task {task_id} not found",
        )

    return ActionResponse(
        status="ok",
        message=f"Message sent to task {task_id}",
        task_id=task_id,
    )


@router.post("/{task_id}/respond", response_model=ActionResponse)
async def respond_to_permission(
    task_id: int,
    request: TaskRespondRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Respond to a Claude permission prompt.

    Use this when the task is in 'waiting' status.
    """
    task = get_task_or_404(db, task_id)

    if task.status != TaskStatus.waiting:
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, not waiting for permission",
        )

    tmux = TmuxService()

    try:
        tmux.send_confirmation(task_id, request.confirm)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Tmux session for task {task_id} not found",
        )

    # Status will be updated by the Stop hook when Claude responds
    task.permission_prompt = None
    db.add(task)
    db.commit()

    action = "approved" if request.confirm else "denied"
    return ActionResponse(
        status="ok",
        message=f"Permission {action} for task {task_id}",
        task_id=task_id,
    )


@router.post("/{task_id}/complete", response_model=ActionResponse)
async def complete_task(
    task_id: int,
    request: TaskCompleteRequest = TaskCompleteRequest(),
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Complete a task.

    This:
    1. Kills the tmux session
    2. Clears hooks configuration
    3. Marks the task as completed

    The GitButler stack is preserved with all commits.
    """
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only complete running tasks",
        )

    tmux = TmuxService()
    hooks = HooksService()

    # Kill tmux session
    try:
        tmux.kill_task_session(task_id)
    except SessionNotFoundError:
        pass  # Already gone

    # Clear hooks
    hooks.teardown_hooks()

    # Cleanup context files from /tmp
    cleanup_task_context(task_id)

    # Update task
    task.status = TaskStatus.completed
    task.claude_status = ClaudeStatus.stopped
    task.claude_session_id = None
    task.completed_at = datetime.now(timezone.utc)
    task.result = request.result

    db.add(task)
    db.commit()

    return ActionResponse(
        status="ok",
        message=f"Task {task_id} completed",
        task_id=task_id,
    )


@router.post("/{task_id}/fail", response_model=ActionResponse)
async def fail_task(
    task_id: int,
    request: TaskFailRequest = TaskFailRequest(),
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Mark a task as failed.

    This:
    1. Kills the tmux session
    2. Clears hooks configuration
    3. Optionally deletes the GitButler stack
    4. Marks the task as failed
    """
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting, TaskStatus.pending):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, cannot fail",
        )

    tmux = TmuxService()
    hooks = HooksService()
    gitbutler = GitButlerService()

    # Kill tmux session if it exists
    try:
        tmux.kill_task_session(task_id)
    except SessionNotFoundError:
        pass

    # Clear hooks
    hooks.teardown_hooks()

    # Cleanup context files from /tmp
    cleanup_task_context(task_id)

    # Optionally delete stack
    if request.delete_stack and task.stack_name:
        try:
            gitbutler.delete_stack(task.stack_name)
            task.stack_name = None
            task.stack_id = None
        except GitButlerError:
            pass  # Stack might not exist

    # Update task
    task.status = TaskStatus.failed
    task.claude_status = ClaudeStatus.stopped
    task.claude_session_id = None
    task.completed_at = datetime.now(timezone.utc)
    task.result = request.reason

    db.add(task)
    db.commit()

    return ActionResponse(
        status="ok",
        message=f"Task {task_id} marked as failed",
        task_id=task_id,
    )


@router.get("/{task_id}/output")
async def get_task_output(
    task_id: int,
    lines: int = 100,
    db: Session = Depends(get_db),
) -> dict:
    """Get recent terminal output from the task's tmux session."""
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, no active session",
        )

    tmux = TmuxService()

    try:
        output = tmux.capture_output(task_id, lines=lines)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Tmux session for task {task_id} not found",
        )

    return {
        "task_id": task_id,
        "output": output,
        "lines": lines,
    }
