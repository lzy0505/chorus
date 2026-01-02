"""Task API endpoints for full task lifecycle management.

Tasks are the primary entity in Chorus. Each task:
- Runs in its own tmux process
- Has its own GitButler stack (virtual branch)
- Can have Claude restarted without losing context
"""

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus, ClaudeStatus
from services.tmux import TmuxService, SessionExistsError, SessionNotFoundError, get_transcript_dir
from services.gitbutler import GitButlerService, StackExistsError, GitButlerError
from services.hooks import HooksService
from services.context import write_task_context, cleanup_task_context, get_context_file
from services.logging_utils import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# Request/Response models
class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: str
    description: str = ""
    priority: int = 0
    permission_profile: str = "full_dev"  # read_only, safe_edit, full_dev, git_only


class TaskUpdate(BaseModel):
    """Request body for updating a task."""

    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None


class TaskResponse(BaseModel):
    """Response model for task data."""

    id: UUID
    title: str
    description: str
    priority: int
    status: TaskStatus
    stack_name: Optional[str]
    tmux_session: Optional[str]
    claude_status: ClaudeStatus
    claude_session_id: Optional[str]
    claude_restarts: int
    continuation_count: int
    prompt_history: str
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


class TaskContinueRequest(BaseModel):
    """Request body for continuing a task with a new prompt."""

    prompt: str


class ActionResponse(BaseModel):
    """Response for action endpoints."""

    status: str
    message: str
    task_id: UUID


# Helper functions
def get_task_or_404(db: Session, task_id: UUID) -> Task:
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
    logger.info(f"Creating task: {task_data.title}")

    # Get permission policy from profile
    from services.claude_config import get_permission_profile
    permission_policy = get_permission_profile(task_data.permission_profile)

    task = Task(
        title=task_data.title,
        description=task_data.description,
        priority=task_data.priority,
        permission_policy=json.dumps(permission_policy),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"Created task {task.id}: {task.title} (permission_profile={task_data.permission_profile})")
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
    task_id: UUID,
    db: Session = Depends(get_db),
) -> Task:
    """Get a task by ID."""
    return get_task_or_404(db, task_id)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
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
    task_id: UUID,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Delete a task.

    Only pending or failed tasks can be deleted. Running tasks must be
    completed or failed first.
    """
    logger.info(f"Deleting task {task_id}")
    task = get_task_or_404(db, task_id)

    if task.status in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete running task. Complete or fail it first.",
        )

    # Cleanup task-specific Claude config
    from services.claude_config import cleanup_task_claude_config
    cleanup_task_claude_config(task_id)

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
    task_id: UUID,
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
    logger.info(f"Starting task {task_id}")
    task = get_task_or_404(db, task_id)

    if task.status != TaskStatus.pending:
        logger.warning(f"Cannot start task {task_id}: status is {task.status}")
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
        task.stack_cli_id = stack.cli_id
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
        session_id = tmux.get_session_id(task_id)
        task.tmux_session = session_id

    # 3. Ensure hooks config exists (shared across all sessions)
    hooks.ensure_hooks()

    # 3b. Create task-specific Claude config with permission hooks
    from services.claude_config import create_task_claude_config, get_default_permission_policy

    # Use task's permission policy if set, otherwise use default
    if task.permission_policy:
        try:
            policy = json.loads(task.permission_policy)
        except json.JSONDecodeError:
            logger.warning(f"Invalid permission_policy JSON for task {task_id}, using default")
            policy = get_default_permission_policy()
    else:
        policy = get_default_permission_policy()
        task.permission_policy = json.dumps(policy)

    create_task_claude_config(task_id, permission_policy=policy)
    logger.info(f"Created task-specific Claude config with permission policy")

    # 4. Update task status
    task.status = TaskStatus.running
    task.claude_status = ClaudeStatus.starting
    task.started_at = datetime.now(timezone.utc)

    # Add initial user prompt to log
    kickoff_message = request.initial_prompt or "Complete the HIGHEST PRIORITY task."
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    task.last_output = f"[{timestamp}] 👤 You: {kickoff_message}"

    # Record initial prompt in history
    prompts = [kickoff_message]
    task.prompt_history = json.dumps(prompts)

    db.add(task)
    db.commit()
    db.refresh(task)

    # 5. Write task context to /tmp (not in project directory)
    context_file = write_task_context(task, user_prompt=request.initial_prompt)

    # 6. Start Claude in tmux with context injected via --append-system-prompt

    # Use JSON mode if enabled in config
    from config import get_config
    config = get_config()
    logger.info(f"Task {task_id}: use_json_mode={config.monitoring.use_json_mode}")
    if config.monitoring.use_json_mode:
        tmux.start_claude_json_mode(
            task_id,
            initial_prompt=kickoff_message,
            context_file=context_file
        )
    else:
        tmux.start_claude(
            task_id,
            initial_prompt=kickoff_message,
            context_file=context_file
        )

    logger.info(f"Task {task_id} started successfully with stack '{task.stack_name}'")
    return ActionResponse(
        status="ok",
        message=f"Task {task_id} started with stack '{task.stack_name}'",
        task_id=task_id,
    )


@router.post("/{task_id}/restart-claude", response_model=ActionResponse)
async def restart_claude(
    task_id: UUID,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Restart Claude in the task's tmux session.

    Use this when Claude hangs, crashes, or loses context.
    The tmux session and GitButler stack are preserved.
    """
    logger.info(f"Restarting Claude for task {task_id}")
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only restart running tasks",
        )

    tmux = TmuxService()

    # Get context file path (context was written when task started)
    context_file = get_context_file(task_id)

    # Send a kickoff message to get Claude working after restart
    kickoff_message = "Continue to complete the HIGHEST PRIORITY task."

    # Use JSON mode if enabled in config
    from config import get_config
    config = get_config()

    try:
        if config.monitoring.use_json_mode:
            # In JSON mode, kill Claude and restart with JSON mode
            # The restart_claude method sends Ctrl-C and relaunches, but we need JSON mode
            import subprocess
            import time
            session_id = tmux.get_session_id(task_id)

            # Send Ctrl-C to interrupt
            subprocess.run(["tmux", "send-keys", "-t", session_id, "C-c"], check=False)
            time.sleep(0.2)
            subprocess.run(["tmux", "send-keys", "-t", session_id, "C-c"], check=False)
            time.sleep(0.3)

            # Start in JSON mode with resume if available
            tmux.start_claude_json_mode(
                task_id,
                initial_prompt=kickoff_message,
                context_file=context_file,
                resume_session_id=task.claude_session_id
            )
        else:
            # Use legacy restart method
            tmux.restart_claude(task_id, context_file=context_file, initial_prompt=kickoff_message)
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

    logger.info(f"Claude restarted for task {task_id} (restart #{task.claude_restarts})")
    return ActionResponse(
        status="ok",
        message=f"Claude restarted for task {task_id} (restart #{task.claude_restarts})",
        task_id=task_id,
    )


@router.post("/{task_id}/continue", response_model=ActionResponse)
async def continue_task(
    task_id: UUID,
    request: TaskContinueRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Continue a task with a new prompt using --resume.

    This is used for multi-step tasks where Claude has stopped after completing
    one step. Uses the saved claude_session_id to resume the session.

    The task must be running but Claude must be stopped.
    """
    logger.info(f"Continuing task {task_id} with new prompt: {request.prompt[:50]}...")
    task = get_task_or_404(db, task_id)

    # Validate task state
    if task.status != TaskStatus.running:
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only continue running tasks",
        )

    if task.claude_status != ClaudeStatus.stopped:
        raise HTTPException(
            status_code=400,
            detail=f"Claude is {task.claude_status}, can only continue when stopped",
        )

    if not task.claude_session_id:
        raise HTTPException(
            status_code=400,
            detail="No session ID available. Use 'Restart Claude' instead.",
        )

    # Update prompt history
    try:
        prompts = json.loads(task.prompt_history) if task.prompt_history else []
    except json.JSONDecodeError:
        prompts = []

    prompts.append(request.prompt)
    task.prompt_history = json.dumps(prompts)
    task.continuation_count += 1

    # Update task state
    task.claude_status = ClaudeStatus.starting
    task.permission_prompt = None

    db.add(task)
    db.commit()

    # Get context file and start Claude with resume
    context_file = get_context_file(task_id)
    tmux = TmuxService()

    # Use JSON mode if enabled in config
    from config import get_config
    config = get_config()

    try:
        if config.monitoring.use_json_mode:
            tmux.start_claude_json_mode(
                task_id,
                initial_prompt=request.prompt,
                context_file=context_file,
                resume_session_id=task.claude_session_id
            )
        else:
            # Legacy mode doesn't support resume
            raise HTTPException(
                status_code=400,
                detail="Task continuation requires JSON mode to be enabled",
            )
    except SessionNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Tmux session for task {task_id} not found",
        )

    logger.info(f"Task {task_id} continued with prompt (continuation #{task.continuation_count})")
    return ActionResponse(
        status="ok",
        message=f"Task continued with new prompt (continuation #{task.continuation_count})",
        task_id=task_id,
    )


@router.post("/{task_id}/send", response_model=ActionResponse)
async def send_message(
    task_id: UUID,
    request: TaskSendRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Send a message to Claude in the task's tmux session."""
    logger.info(f"Sending message to task {task_id}: {request.message[:50]}...")
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

    # Use JSON mode if enabled in config
    from config import get_config
    config = get_config()

    if config.monitoring.use_json_mode and task.claude_session_id:
        # In JSON mode, use --resume to continue the session
        try:
            # Get context file if it exists
            from services.context import get_context_file, context_exists
            context_file = get_context_file(task_id) if context_exists(task_id) else None

            tmux.start_claude_json_mode(
                task_id,
                initial_prompt=request.message,
                context_file=context_file,
                resume_session_id=task.claude_session_id
            )
        except SessionNotFoundError:
            raise HTTPException(
                status_code=500,
                detail=f"Tmux session for task {task_id} not found",
            )
    else:
        # Legacy mode or no session ID yet - just send keys
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
    task_id: UUID,
    request: TaskRespondRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Respond to a Claude permission prompt.

    Use this when the task is in 'waiting' status.
    """
    logger.info(f"Responding to permission prompt for task {task_id}: {'confirm' if request.confirm else 'deny'}")
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
    task_id: UUID,
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
    logger.info(f"Completing task {task_id}")
    task = get_task_or_404(db, task_id)

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        raise HTTPException(
            status_code=400,
            detail=f"Task is {task.status}, can only complete running tasks",
        )

    tmux = TmuxService()
    gitbutler = GitButlerService()

    # Call GitButler stop hook before cleanup
    transcript_dir = get_transcript_dir(task_id)
    transcript_path = str(transcript_dir / "transcript.json")

    try:
        gitbutler.call_stop_hook(
            session_id=str(task_id),
            transcript_path=transcript_path
        )
        logger.info(f"Called stop hook for task {task_id}")
    except Exception as e:
        logger.error(f"Stop hook failed: {e}", exc_info=True)

    # Kill tmux session (this also cleans up transcript directory)
    try:
        tmux.kill_task_session(task_id)
    except SessionNotFoundError:
        pass  # Already gone

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

    logger.info(f"Task {task_id} marked as completed")
    return ActionResponse(
        status="ok",
        message=f"Task {task_id} completed",
        task_id=task_id,
    )


@router.post("/{task_id}/fail", response_model=ActionResponse)
async def fail_task(
    task_id: UUID,
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
    gitbutler = GitButlerService()

    # Kill tmux session if it exists
    try:
        tmux.kill_task_session(task_id)
    except SessionNotFoundError:
        pass

    # Cleanup context files from /tmp
    cleanup_task_context(task_id)

    # Optionally delete stack
    if request.delete_stack and task.stack_name:
        try:
            gitbutler.delete_stack(task.stack_name)
            task.stack_name = None
            task.stack_cli_id = None
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
    task_id: UUID,
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
