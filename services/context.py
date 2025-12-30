"""Task context service for injecting task-specific context into Claude Code sessions.

Context files are stored in /tmp/chorus/task-{id}/ to keep the working directory clean.
The context is injected via Claude's --append-system-prompt flag at startup.
"""

import shutil
from pathlib import Path
from typing import Optional

from models import Task

# Base directory for task context files (outside project)
CONTEXT_BASE_DIR = Path("/tmp/chorus")


def get_context_dir(task_id: int) -> Path:
    """Get the context directory for a task."""
    return CONTEXT_BASE_DIR / f"task-{task_id}"


def get_context_file(task_id: int) -> Path:
    """Get the context file path for a task."""
    return get_context_dir(task_id) / "context.md"


def build_task_context(task: Task, user_prompt: Optional[str] = None) -> str:
    """Build the context string for a task.

    This creates a structured context that Claude will see in its system prompt.
    It includes task metadata, description, and any user-provided instructions.

    Args:
        task: The task to build context for.
        user_prompt: Optional additional instructions from the user.

    Returns:
        Formatted context string.
    """
    sections = []

    # Priority emphasis
    sections.append("🔴 **HIGHEST PRIORITY TASK**")
    sections.append("")

    # Task header
    sections.append(f"# Current Task: {task.title}")
    sections.append(f"Task ID: {task.id}")
    sections.append("")  # Blank line

    # Task description
    if task.description:
        sections.append("## Description")
        sections.append(task.description)
        sections.append("")

    # User prompt / additional instructions
    if user_prompt:
        sections.append("## Instructions")
        sections.append(user_prompt)
        sections.append("")

    return "\n".join(sections)


def write_task_context(
    task: Task,
    user_prompt: Optional[str] = None,
) -> Path:
    """Write task context to a file in /tmp.

    Creates /tmp/chorus/task-{id}/context.md with the task context.
    This file is used with Claude's --append-system-prompt flag.

    Args:
        task: The task to write context for.
        user_prompt: Optional additional instructions.

    Returns:
        Path to the context file.
    """
    context_dir = get_context_dir(task.id)
    context_dir.mkdir(parents=True, exist_ok=True)

    context_file = get_context_file(task.id)
    context_content = build_task_context(task, user_prompt)
    context_file.write_text(context_content)

    return context_file


def cleanup_task_context(task_id: int) -> None:
    """Remove the context directory for a task.

    Called when a task is completed or failed.

    Args:
        task_id: The task ID to clean up.
    """
    context_dir = get_context_dir(task_id)
    if context_dir.exists():
        shutil.rmtree(context_dir)


def context_exists(task_id: int) -> bool:
    """Check if context file exists for a task."""
    return get_context_file(task_id).exists()
