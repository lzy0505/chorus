"""Claude status detection service.

Detects Claude's actual status by analyzing terminal output patterns,
rather than inferring from user actions or relying solely on hooks.
"""

import re
from typing import Optional

from config import get_config
from models import ClaudeStatus
from services.tmux import TmuxService, SessionNotFoundError


class StatusDetector:
    """Detects Claude's actual status from terminal output.

    Uses pattern matching against terminal output to determine if Claude is:
    - idle (at prompt, waiting for input)
    - busy (processing, no prompt visible)
    - waiting (asking for permission)

    This is more reliable than inferring status from user actions.
    """

    def __init__(self, tmux: Optional[TmuxService] = None):
        """Initialize the status detector.

        Args:
            tmux: TmuxService instance (creates new one if not provided)
        """
        self.tmux = tmux or TmuxService()
        config = get_config()
        self.idle_patterns = config.status_patterns.idle
        self.waiting_patterns = config.status_patterns.waiting

    def detect_status(self, task_id: int, lines: int = 50) -> Optional[ClaudeStatus]:
        """Detect Claude's current status from terminal output.

        Args:
            task_id: The task ID to check
            lines: Number of terminal lines to analyze

        Returns:
            Detected ClaudeStatus, or None if session doesn't exist
        """
        try:
            output = self.tmux.capture_output(task_id, lines=lines)
        except SessionNotFoundError:
            return None

        if not output:
            return ClaudeStatus.stopped

        # Check last few lines for status indicators
        # (prompts and permission requests appear at the end)
        last_lines = "\n".join(output.split("\n")[-10:])

        # Check for waiting status first (permission prompts)
        for pattern in self.waiting_patterns:
            if re.search(pattern, last_lines):
                return ClaudeStatus.waiting

        # Check for idle status (prompt visible)
        for pattern in self.idle_patterns:
            if re.search(pattern, last_lines):
                return ClaudeStatus.idle

        # If no patterns match, Claude is busy (processing)
        return ClaudeStatus.busy

    def is_claude_running(self, task_id: int) -> bool:
        """Check if Claude process appears to be running in the session.

        Args:
            task_id: The task ID to check

        Returns:
            True if Claude appears to be running
        """
        try:
            output = self.tmux.capture_output(task_id, lines=20)
            # Look for Claude-specific indicators in output
            # (prompt, tool usage, responses, etc.)
            return bool(output and (">" in output or "claude" in output.lower()))
        except SessionNotFoundError:
            return False
