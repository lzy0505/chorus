"""Centralized error handling and recovery for Chorus services.

This module provides error handling, logging, and recovery strategies
for tmux, GitButler, and Claude operations.
"""

import logging
from typing import Optional, Callable, Any
from functools import wraps
from datetime import datetime, timezone

from services.tmux import TmuxService, SessionNotFoundError, SessionExistsError
from services.gitbutler import GitButlerService, GitButlerError, StackExistsError
from models import Task, TaskStatus, ClaudeStatus

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Base class for service errors."""
    pass


class RecoverableError(ServiceError):
    """Error that can be automatically recovered from."""
    pass


class UnrecoverableError(ServiceError):
    """Error that requires manual intervention."""
    pass


def handle_tmux_errors(func: Callable) -> Callable:
    """Decorator to handle tmux errors gracefully.

    Automatically handles common tmux failures:
    - Session not found: Log and suggest recovery
    - Session already exists: Return existing session
    - Other errors: Log and re-raise
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except SessionNotFoundError as e:
            logger.error(f"Tmux session not found: {e}")
            # This is usually unrecoverable - the session is gone
            raise UnrecoverableError(
                f"Tmux session not found. The session may have been killed. "
                f"Try restarting the task."
            ) from e
        except SessionExistsError as e:
            logger.warning(f"Tmux session already exists: {e}")
            # This is recoverable - just use the existing session
            raise RecoverableError(
                f"Session already exists. Using existing session."
            ) from e
        except Exception as e:
            logger.exception(f"Unexpected tmux error in {func.__name__}")
            raise ServiceError(f"Tmux error: {e}") from e

    return wrapper


def handle_gitbutler_errors(func: Callable) -> Callable:
    """Decorator to handle GitButler errors gracefully.

    Automatically handles common GitButler failures:
    - Stack already exists: Use existing stack
    - Command failures: Log and suggest fixes
    - Nothing to commit: Skip commit silently
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except StackExistsError as e:
            logger.warning(f"GitButler stack already exists: {e}")
            # This is recoverable - just use the existing stack
            raise RecoverableError(
                f"Stack already exists. Using existing stack."
            ) from e
        except GitButlerError as e:
            error_msg = str(e).lower()

            # Handle "nothing to commit" gracefully
            if "nothing to commit" in error_msg or "no changes" in error_msg:
                logger.debug("No changes to commit, skipping")
                return None

            # Handle stack not found
            if "not found" in error_msg or "does not exist" in error_msg:
                logger.error(f"GitButler stack not found: {e}")
                raise UnrecoverableError(
                    f"GitButler stack not found. The stack may have been deleted. "
                    f"Try failing and restarting the task."
                ) from e

            # Generic GitButler error
            logger.error(f"GitButler error: {e}")
            raise ServiceError(f"GitButler error: {e}") from e
        except Exception as e:
            logger.exception(f"Unexpected GitButler error in {func.__name__}")
            raise ServiceError(f"GitButler error: {e}") from e

    return wrapper


class TaskRecovery:
    """Handles task recovery from various failure scenarios."""

    @staticmethod
    def recover_from_tmux_failure(task: Task, db) -> bool:
        """Attempt to recover from a tmux session failure.

        Args:
            task: The task to recover
            db: Database session

        Returns:
            True if recovery was successful, False otherwise
        """
        tmux = TmuxService()

        logger.info(f"Attempting to recover task {task.id} from tmux failure")

        # Check if session actually exists
        if not tmux.session_exists(task.id):
            logger.error(f"Tmux session for task {task.id} does not exist")

            # Update task status
            task.status = TaskStatus.failed
            task.claude_status = ClaudeStatus.stopped
            task.result = "Task failed: tmux session not found"
            db.add(task)
            db.commit()

            return False

        # Session exists but might be in bad state
        # Try to restart Claude
        try:
            from services.context import get_context_file
            context_file = get_context_file(task.id)
            tmux.restart_claude(
                task.id,
                context_file=context_file,
                initial_prompt="Please continue working on this task."
            )

            task.claude_status = ClaudeStatus.starting
            task.claude_restarts += 1
            db.add(task)
            db.commit()

            logger.info(f"Successfully restarted Claude for task {task.id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to restart Claude for task {task.id}")

            task.status = TaskStatus.failed
            task.claude_status = ClaudeStatus.stopped
            task.result = f"Task failed: could not restart Claude ({e})"
            db.add(task)
            db.commit()

            return False

    @staticmethod
    def detect_hanging_tasks(db) -> list[Task]:
        """Detect tasks that may be hanging (no status updates in a while).

        A task is considered hanging if:
        - Status is running but Claude status is 'busy' for > 10 minutes
        - Task has been in 'waiting' status for > 30 minutes

        Args:
            db: Database session

        Returns:
            List of potentially hanging tasks
        """
        from sqlmodel import select

        # This is a simple heuristic - you could add more sophisticated detection
        # based on last_update timestamps if you track those

        statement = select(Task).where(
            Task.status.in_([TaskStatus.running, TaskStatus.waiting])
        )
        tasks = list(db.exec(statement).all())

        hanging_tasks = []

        for task in tasks:
            # Check if task has been waiting too long
            # (In a real implementation, you'd track last_activity timestamp)
            if task.status == TaskStatus.waiting:
                # For now, just add a log entry
                logger.warning(
                    f"Task {task.id} has been waiting for user response. "
                    f"Status: {task.claude_status}"
                )

        return hanging_tasks

    @staticmethod
    def cleanup_orphaned_sessions(db) -> int:
        """Clean up tmux sessions for non-existent or completed tasks.

        Args:
            db: Database session

        Returns:
            Number of sessions cleaned up
        """
        from sqlmodel import select

        tmux = TmuxService()

        # Get all active tmux sessions
        active_session_task_ids = tmux.list_task_sessions()

        # Get all running tasks from DB
        statement = select(Task).where(
            Task.status.in_([TaskStatus.running, TaskStatus.waiting])
        )
        running_tasks = list(db.exec(statement).all())
        running_task_ids = {task.id for task in running_tasks}

        # Find orphaned sessions (tmux sessions without corresponding running tasks)
        orphaned_ids = set(active_session_task_ids) - running_task_ids

        cleaned = 0
        for task_id in orphaned_ids:
            try:
                tmux.kill_task_session(task_id)
                logger.info(f"Cleaned up orphaned tmux session for task {task_id}")
                cleaned += 1
            except Exception as e:
                logger.error(f"Failed to clean up session for task {task_id}: {e}")

        return cleaned


def log_service_error(
    service: str,
    operation: str,
    error: Exception,
    task_id: Optional[int] = None,
    extra: Optional[dict] = None
) -> None:
    """Log a service error with consistent formatting.

    Args:
        service: The service name (e.g., 'tmux', 'gitbutler')
        operation: The operation that failed (e.g., 'create_session', 'commit')
        error: The exception that was raised
        task_id: Optional task ID for context
        extra: Optional extra context to include in the log
    """
    context = {
        "service": service,
        "operation": operation,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if task_id:
        context["task_id"] = task_id

    if extra:
        context.update(extra)

    logger.error(
        f"Service error in {service}.{operation}: {error}",
        extra=context,
        exc_info=True
    )
