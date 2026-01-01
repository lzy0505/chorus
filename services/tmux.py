"""Tmux service for task-centric session management.

Each task gets its own tmux session where Claude Code runs.
The tmux session persists even if Claude crashes/hangs, allowing restarts.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from config import get_config
from services.hooks import get_hooks_config_dir
from services.logging_utils import get_logger, log_subprocess_call

logger = get_logger(__name__)


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
    task_id: UUID
    exists: bool
    has_claude_process: bool = False


def _session_id_for_task(task_id: UUID) -> str:
    """Generate tmux session ID for a task."""
    config = get_config()
    return f"{config.tmux.session_prefix}-task-{task_id}"


def _run_tmux(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a tmux command."""
    cmd = ["tmux"] + args
    log_subprocess_call(logger, cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        log_subprocess_call(logger, cmd, result=result)
        return result
    except Exception as e:
        log_subprocess_call(logger, cmd, error=e)
        raise


def session_exists(session_id: str) -> bool:
    """Check if a tmux session exists."""
    result = _run_tmux(["has-session", "-t", session_id], check=False)
    return result.returncode == 0


def get_transcript_dir(task_id: UUID) -> Path:
    """Get the transcript directory path for a task.

    Args:
        task_id: The task UUID.

    Returns:
        Path to transcript directory: /tmp/chorus/task-{uuid}/
    """
    return Path(f"/tmp/chorus/task-{task_id}")


def create_transcript_file(task_id: UUID, project_root: str) -> Path:
    """Create a minimal transcript file for GitButler hooks.

    GitButler hooks expect a transcript directory containing a session transcript.
    We create a minimal JSONL file with one user message entry.

    Args:
        task_id: The task UUID (used as GitButler session_id).
        project_root: The project working directory.

    Returns:
        Path to the created transcript file.
    """
    transcript_dir = get_transcript_dir(task_id)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    transcript_file = transcript_dir / "transcript.json"

    # Create minimal transcript entry (JSONL format - one JSON object per line)
    entry = {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": project_root,
        "sessionId": str(task_id),
        "version": "1.0.0",
        "gitBranch": "",
        "type": "user",
        "message": {
            "role": "user",
            "content": "Task initialized"
        },
        "uuid": "00000000-0000-0000-0000-000000000000",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    # Write as JSONL (one JSON object per line)
    with open(transcript_file, "w") as f:
        f.write(json.dumps(entry) + "\n")

    logger.debug(f"Created transcript file: {transcript_file}")
    return transcript_file


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

    def get_session_id(self, task_id: UUID) -> str:
        """Get the tmux session ID for a task."""
        return _session_id_for_task(task_id)

    def session_exists(self, task_id: UUID) -> bool:
        """Check if the tmux session for a task exists."""
        return session_exists(self.get_session_id(task_id))

    def create_task_session(self, task_id: UUID) -> str:
        """Create a new tmux session for a task.

        Also creates the transcript directory and file for GitButler hooks.

        Args:
            task_id: The task UUID to create a session for.

        Returns:
            The session ID (e.g., 'chorus-task-{uuid}')

        Raises:
            SessionExistsError: If the session already exists.
        """
        session_id = self.get_session_id(task_id)

        if session_exists(session_id):
            raise SessionExistsError(f"Session {session_id} already exists")

        logger.info(f"Creating tmux session for task {task_id}: {session_id}")

        # Create transcript file for GitButler hooks
        create_transcript_file(task_id, self.project_root)

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

        logger.info(f"Created tmux session: {session_id}")
        return session_id

    def start_claude(
        self,
        task_id: UUID,
        initial_prompt: Optional[str] = None,
        context_file: Optional[Path] = None,
    ) -> None:
        """Start Claude Code in the task's tmux session.

        Args:
            task_id: The task ID.
            initial_prompt: Optional prompt to send after Claude starts.
            context_file: Optional path to context file for --append-system-prompt.
                         Context is injected into Claude's system prompt at startup.
                         The file should be in /tmp/chorus/task-{id}/ to avoid
                         polluting the working directory.

        Raises:
            SessionNotFoundError: If the tmux session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        logger.info(f"Starting Claude Code for task {task_id} in session {session_id}")

        # Get shared config directory for hooks
        # This keeps hooks out of the hosted project's .claude/ directory
        config_dir = get_hooks_config_dir()

        # Build the claude command with isolated config
        # Pass through CLAUDE_CODE_OAUTH_TOKEN if set (for headless auth)
        # See: https://github.com/anthropics/claude-code/issues/8938
        env_vars = [f'CLAUDE_CONFIG_DIR="{config_dir}"']
        oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if oauth_token:
            env_vars.append(f'CLAUDE_CODE_OAUTH_TOKEN="{oauth_token}"')
        env_prefix = " ".join(env_vars)

        # Build Claude command with context and initial prompt
        if context_file and context_file.exists():
            # Use --append-system-prompt to inject task context
            # The context becomes part of Claude's system prompt for the entire session
            claude_cmd = f'{env_prefix} claude --append-system-prompt "$(cat {context_file})"'
            logger.debug(f"Starting Claude with context file: {context_file}")
        else:
            claude_cmd = f"{env_prefix} claude"

        # If there's an initial prompt, pass it using -p flag
        # This is more reliable than waiting and sending keys via tmux
        if initial_prompt:
            # Escape the prompt for shell
            escaped_prompt = initial_prompt.replace('"', '\\"')
            claude_cmd += f' -p "{escaped_prompt}"'
            logger.debug(f"Starting Claude with initial prompt: {initial_prompt[:100]}...")

        # Send the claude command
        _run_tmux(["send-keys", "-t", session_id, claude_cmd, "Enter"])
        logger.info(f"Claude Code started for task {task_id}")

    def start_claude_json_mode(
        self,
        task_id: UUID,
        initial_prompt: Optional[str] = None,
        context_file: Optional[Path] = None,
        resume_session_id: Optional[str] = None,
    ) -> None:
        """Start Claude Code in JSON stream mode for event parsing.

        Args:
            task_id: The task ID.
            initial_prompt: Optional prompt to send after Claude starts.
            context_file: Optional path to context file for --append-system-prompt.
            resume_session_id: Optional session ID for --resume flag.

        Raises:
            SessionNotFoundError: If the tmux session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        logger.info(f"Starting Claude Code (JSON mode) for task {task_id} in session {session_id}")

        # JSON mode: Don't use hooks config directory - hooks interfere with JSON output!
        # Just use default Claude config or environment variables
        env_vars = []
        oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if oauth_token:
            env_vars.append(f'CLAUDE_CODE_OAUTH_TOKEN="{oauth_token}"')
        env_prefix = " ".join(env_vars) if env_vars else ""

        # Build Claude command with JSON output format
        # Note: --verbose is required when using -p with --output-format stream-json
        # Use --permission-mode acceptEdits to auto-approve file edits (still prompts for Bash)
        if context_file and context_file.exists():
            base_cmd = 'claude --append-system-prompt "$(cat {context_file})" --output-format stream-json --verbose --permission-mode acceptEdits'.format(context_file=context_file)
            logger.debug(f"Starting Claude (JSON) with context file: {context_file}")
        else:
            base_cmd = "claude --output-format stream-json --verbose --permission-mode acceptEdits"
            logger.debug("Starting Claude (JSON) with acceptEdits permission mode")

        claude_cmd = f"{env_prefix} {base_cmd}".strip() if env_prefix else base_cmd

        # Add resume flag if session ID provided
        if resume_session_id:
            claude_cmd += f" --resume {resume_session_id}"
            logger.debug(f"Resuming Claude session: {resume_session_id}")

        # If there's an initial prompt, pass it using -p flag
        if initial_prompt:
            escaped_prompt = initial_prompt.replace('"', '\\"')
            claude_cmd += f' -p "{escaped_prompt}"'
            logger.debug(f"Starting Claude with initial prompt: {initial_prompt[:100]}...")

        # Send the claude command
        _run_tmux(["send-keys", "-t", session_id, claude_cmd, "Enter"])
        logger.info(f"Claude Code (JSON mode) started for task {task_id}")

    def restart_claude(
        self,
        task_id: int,
        context_file: Optional[Path] = None,
        initial_prompt: Optional[str] = None,
    ) -> None:
        """Restart Claude in the task's tmux session.

        Sends Ctrl-C to interrupt, then relaunches Claude.
        If context_file is provided, re-injects the task context.

        Args:
            task_id: The task ID.
            context_file: Optional path to context file for --append-system-prompt.
            initial_prompt: Optional prompt to send after Claude restarts.

        Raises:
            SessionNotFoundError: If the tmux session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        logger.info(f"Restarting Claude Code for task {task_id}")

        # Send Ctrl-C to interrupt any running process
        _run_tmux(["send-keys", "-t", session_id, "C-c"])
        time.sleep(0.2)

        # Send another Ctrl-C in case Claude needs confirmation to exit
        _run_tmux(["send-keys", "-t", session_id, "C-c"])
        time.sleep(0.3)

        # Get shared config directory for hooks
        config_dir = get_hooks_config_dir()

        # Build the claude command with isolated config (same logic as start_claude)
        # Pass through CLAUDE_CODE_OAUTH_TOKEN if set (for headless auth)
        env_vars = [f'CLAUDE_CONFIG_DIR="{config_dir}"']
        oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if oauth_token:
            env_vars.append(f'CLAUDE_CODE_OAUTH_TOKEN="{oauth_token}"')
        env_prefix = " ".join(env_vars)

        # Build Claude command with context and initial prompt
        if context_file and context_file.exists():
            claude_cmd = f'{env_prefix} claude --append-system-prompt "$(cat {context_file})"'
        else:
            claude_cmd = f"{env_prefix} claude"

        # If there's an initial prompt, pass it directly to Claude as an argument
        # This is more reliable than waiting and sending keys via tmux
        if initial_prompt:
            # Escape the prompt for shell
            escaped_prompt = initial_prompt.replace('"', '\\"')
            claude_cmd += f' "{escaped_prompt}"'

        # Start Claude again
        _run_tmux(["send-keys", "-t", session_id, claude_cmd, "Enter"])
        logger.info(f"Claude Code restarted for task {task_id}")

    def kill_task_session(self, task_id: UUID) -> None:
        """Kill the tmux session for a task and cleanup transcript directory.

        Args:
            task_id: The task UUID.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        logger.info(f"Killing tmux session for task {task_id}: {session_id}")
        _run_tmux(["kill-session", "-t", session_id])
        logger.info(f"Killed tmux session: {session_id}")

        # Cleanup transcript directory
        transcript_dir = get_transcript_dir(task_id)
        if transcript_dir.exists():
            shutil.rmtree(transcript_dir, ignore_errors=True)
            logger.debug(f"Cleaned up transcript directory: {transcript_dir}")

    def capture_output(self, task_id: UUID, lines: int = 100) -> str:
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

    def capture_json_events(self, task_id: UUID) -> str:
        """Capture JSON events from the task's tmux session.

        This method is specifically for capturing output from Claude running
        in --output-format stream-json mode.

        Args:
            task_id: The task ID.

        Returns:
            The captured terminal output containing JSON events.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session_id = self.get_session_id(task_id)

        if not session_exists(session_id):
            raise SessionNotFoundError(f"Session {session_id} not found")

        # Capture more lines to get all JSON events
        # -S - captures entire scrollback history (up to tmux's history limit)
        # -p prints to stdout
        result = _run_tmux(
            ["capture-pane", "-t", session_id, "-p", "-S", "-"],
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""

    def send_keys(self, task_id: UUID, text: str, enter: bool = True) -> None:
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

    def send_confirmation(self, task_id: UUID, confirm: bool) -> None:
        """Respond to a permission prompt.

        Args:
            task_id: The task ID.
            confirm: True for yes, False for no.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        response = "y" if confirm else "n"
        self.send_keys(task_id, response)

    def get_session_info(self, task_id: UUID) -> SessionInfo:
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
