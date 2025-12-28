"""Tmux command wrapper for session management."""

import subprocess
from typing import Optional

from config import SESSION_PREFIX, PROJECT_ROOT


def create_session(name: str, initial_prompt: Optional[str] = None) -> str:
    """Create a new tmux session with Claude Code.

    Args:
        name: Session name (will be prefixed with SESSION_PREFIX)
        initial_prompt: Optional prompt to send immediately

    Returns:
        Session ID (e.g., 'claude-feature-auth')
    """
    session_id = f"{SESSION_PREFIX}-{name}"

    # Create tmux session with claude command
    subprocess.run([
        "tmux", "new-session", "-d",
        "-s", session_id,
        "-c", str(PROJECT_ROOT),
        "claude"
    ], check=True)

    if initial_prompt:
        send_keys(session_id, initial_prompt)

    return session_id


def kill_session(session_id: str) -> None:
    """Kill a tmux session."""
    subprocess.run(["tmux", "kill-session", "-t", session_id], check=True)


def list_sessions() -> list[str]:
    """List all tmux sessions matching our prefix."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return []

    sessions = result.stdout.strip().split("\n")
    return [s for s in sessions if s.startswith(SESSION_PREFIX)]


def capture_output(session_id: str, lines: int = 100) -> str:
    """Capture terminal output from a session."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_id, "-p", "-S", f"-{lines}"],
        capture_output=True,
        text=True
    )
    return result.stdout if result.returncode == 0 else ""


def send_keys(session_id: str, text: str) -> None:
    """Send text to a session."""
    subprocess.run([
        "tmux", "send-keys", "-t", session_id, text, "Enter"
    ], check=True)


def send_confirmation(session_id: str, confirm: bool) -> None:
    """Respond to a permission prompt."""
    response = "y" if confirm else "n"
    subprocess.run([
        "tmux", "send-keys", "-t", session_id, response, "Enter"
    ], check=True)
