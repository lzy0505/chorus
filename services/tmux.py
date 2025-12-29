"""Tmux service for task-centric session management.

Each task gets its own tmux session where Claude Code runs.
The tmux session persists even if Claude crashes/hangs, allowing restarts.
"""

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from config import get_config


class TmuxError(Exception):
    """Base exception for tmux operations."""

    pass


class SessionNotFoundError(TmuxError):
    """Raised when a tmux session doesn't exist."""

    pass


class SessionExistsError(TmuxError):
    """Raised when trying to create a session that already exists."""

    pass


@dataclass
class SessionInfo:
    """Information about a tmux session."""

    session_id: str
    task_id: int
    exists: bool
    has_claude_process: bool = False


def _session_id_for_task(task_id: int) -> str:
    """Generate tmux session ID for a task."""
    config = get_config()
    return f"{config.tmux.session_prefix}-task-{task_id}"


def _run_tmux(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a tmux command."""
    cmd = ["tmux"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def session_exists(session_id: str) -> bool:
    """Check if a tmux session exists."""
    result = _run_tmux(["has-session", "-t", session_id], check=False)
    return result.returncode == 0


class TmuxService:
    """Task-centric tmux session management.

    Each task has its own tmux session where Claude Code runs.
    The session lifecycle:
    1. create_task_session() - Create tmux session for task
    2. start_claude() - Launch Claude in the session
    3. capture_output() / send_keys() - Interact with Claude
    4. restart_claude() - Kill Claude and relaunch (keeps tmux)
    5. kill_task_session() - Cleanup when task completes
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the tmux service.

        Args:
            project_root: Working directory for sessions. Defaults to config project_root.
        """
        if project_root is None:
            config = get_config()
            project_root = str(config.project_root)
        self.project_root = project_root

    def get_session_id(self, task_id: int) -> str:
        """Get the tmux session ID for a task."""
        return _session_id_for_task(task_id)

    def session_exists(self, task_id: int) -> bool:
        """Check if the tmux session for a task exists."""
        return session_exists(self.get_session_id(task_id))

    def create_task_session(self, task_id: int) -> str:
        """Create a new tmux session for a task.

        Args:
            task_id: The task ID to create a session for.

        Returns:
            The session ID (e.g., 'claude-task-1')

        Raises:
            SessionExistsError: If the session already exists.
        """
        session_id = self.get_session_id(task_id)

        if session_exists(session_id):
            raise SessionExistsError(f"Session {session_id} already exists")

        # Create detached tmux session with shell (not Claude yet)
        _run_tmux(
            [
                "new-session",
                "-d",
                "-s",
                session_id,
                "-c",
                self.project_root,
            ]
        )

        return session_id

    def start_claude(
        self, task_id: int, initial_prompt: Optional[str] = None
    ) -> None:
        """Start Claude Code in the task's tmux session.

        Args:
            task_id: The task ID.
            initial_prompt: Optional prompt to send after Claude starts.

        Raises:
            SessionNotFoundError: If the tmux session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        # Send the claude command
        _run_tmux(["send-keys", "-t", session_id, "claude", "Enter"])

        # If there's an initial prompt, wait a bit for Claude to start
        # then send the prompt
        if initial_prompt:
            time.sleep(0.5)  # Give Claude time to initialize
            self.send_keys(task_id, initial_prompt)

    def restart_claude(self, task_id: int) -> None:
        """Restart Claude in the task's tmux session.

        Sends Ctrl-C to interrupt, then relaunches Claude.

        Args:
            task_id: The task ID.

        Raises:
            SessionNotFoundError: If the tmux session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        # Send Ctrl-C to interrupt any running process
        _run_tmux(["send-keys", "-t", session_id, "C-c"])
        time.sleep(0.2)

        # Send another Ctrl-C in case Claude needs confirmation to exit
        _run_tmux(["send-keys", "-t", session_id, "C-c"])
        time.sleep(0.3)

        # Start Claude again
        _run_tmux(["send-keys", "-t", session_id, "claude", "Enter"])

    def kill_task_session(self, task_id: int) -> None:
        """Kill the tmux session for a task.

        Args:
            task_id: The task ID.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        _run_tmux(["kill-session", "-t", session_id])

    def capture_output(self, task_id: int, lines: int = 100) -> str:
        """Capture terminal output from the task's tmux session.

        Args:
            task_id: The task ID.
            lines: Number of lines to capture from history.

        Returns:
            The captured terminal output.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        result = _run_tmux(
            ["capture-pane", "-t", session_id, "-p", "-S", f"-{lines}"],
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""

    def send_keys(self, task_id: int, text: str, enter: bool = True) -> None:
        """Send text to the task's tmux session.

        Args:
            task_id: The task ID.
            text: Text to send.
            enter: Whether to send Enter after the text.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        args = ["send-keys", "-t", session_id, text]
        if enter:
            args.append("Enter")
        _run_tmux(args)

    def send_confirmation(self, task_id: int, confirm: bool) -> None:
        """Respond to a permission prompt.

        Args:
            task_id: The task ID.
            confirm: True for yes, False for no.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        response = "y" if confirm else "n"
        self.send_keys(task_id, response)

    def get_session_info(self, task_id: int) -> SessionInfo:
        """Get information about a task's tmux session.

        Args:
            task_id: The task ID.

        Returns:
            SessionInfo with session details.
        """
        session_id = self.get_session_id(task_id)
        exists = session_exists(session_id)

        has_claude = False
        if exists:
            # Check if 'claude' process is running in the session
            output = self.capture_output(task_id, lines=5)
            # Simple heuristic: if output contains typical Claude prompts
            has_claude = ">" in output or "claude" in output.lower()

        return SessionInfo(
            session_id=session_id,
            task_id=task_id,
            exists=exists,
            has_claude_process=has_claude,
        )

    def list_task_sessions(self) -> list[int]:
        """List all task IDs that have active tmux sessions.

        Returns:
            List of task IDs with active sessions.
        """
        result = _run_tmux(
            ["list-sessions", "-F", "#{session_name}"], check=False
        )
        if result.returncode != 0:
            return []

        task_ids = []
        config = get_config()
        prefix = f"{config.tmux.session_prefix}-task-"
        for line in result.stdout.strip().split("\n"):
            if line.startswith(prefix):
                try:
                    task_id = int(line[len(prefix) :])
                    task_ids.append(task_id)
                except ValueError:
                    continue
        return task_ids
