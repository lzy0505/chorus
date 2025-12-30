"""Claude Code hooks integration for real-time status updates.

This module generates hook configurations and handles hook events from Claude Code.
Instead of polling terminal output, we use Claude's native hooks for deterministic
status detection.

Hook events used:
- SessionStart: Claude launches → map session to task
- Stop: Claude finishes responding → idle status
- PermissionRequest: Permission dialog shown → waiting status
- SessionEnd: Claude exits → stopped status

Isolation:
Hooks are written to /tmp/chorus/hooks/.claude/ to avoid polluting
the hosted project's working directory. All Claude sessions share the
same hooks config since it contains no task-specific data. Claude Code
is launched with CLAUDE_CONFIG_DIR pointing to this shared location.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import get_config


def get_hooks_config_dir() -> Path:
    """Get shared config directory for all Claude sessions.

    Returns /tmp/chorus/hooks/.claude/
    This keeps hooks isolated from the hosted project while allowing
    all sessions to share the same configuration.
    """
    return Path("/tmp/chorus/hooks/.claude")


@dataclass
class HookPayload:
    """Payload received from Claude Code hooks via stdin.

    Claude Code passes this JSON to hook commands via stdin.
    """

    session_id: str
    hook_event_name: str
    transcript_path: Optional[str] = None
    cwd: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict) -> "HookPayload":
        """Create HookPayload from JSON dict."""
        return cls(
            session_id=data.get("session_id", ""),
            hook_event_name=data.get("hook_event_name", ""),
            transcript_path=data.get("transcript_path"),
            cwd=data.get("cwd"),
        )

    @classmethod
    def from_stdin(cls, stdin_text: str) -> "HookPayload":
        """Parse HookPayload from stdin JSON text."""
        data = json.loads(stdin_text)
        return cls.from_json(data)


def get_chorus_url() -> str:
    """Get the base URL for the Chorus API."""
    config = get_config()
    return f"http://{config.server.host}:{config.server.port}"


def generate_hooks_config(task_id: int, chorus_url: Optional[str] = None) -> dict:
    """Generate Claude Code hooks configuration for a task.

    This creates the hooks section for .claude/settings.json that will
    POST events to the Chorus API.

    Args:
        task_id: The task ID to associate with hook events.
        chorus_url: Override the Chorus API URL (for testing).

    Returns:
        Dict containing the hooks configuration.
    """
    url = chorus_url or get_chorus_url()

    # The hook handler script path (relative to project root)
    handler_script = "python -c \"import sys,json,urllib.request as r; " \
        "d=json.loads(sys.stdin.read()); " \
        f"r.urlopen(r.Request('{url}/api/hooks/' + d['hook_event_name'].lower(), " \
        "json.dumps(d).encode(), {'Content-Type': 'application/json'}))\""

    # Events that don't need a matcher - use simple format
    no_matcher_events = ["SessionStart", "Stop", "SessionEnd"]
    # Events that need a matcher (use "*" for all tools) - use nested format
    matcher_events = ["PermissionRequest", "PostToolUse"]

    hooks_config: dict = {"hooks": {}}

    for event in no_matcher_events:
        hooks_config["hooks"][event] = [
            {"type": "command", "command": handler_script}
        ]

    for event in matcher_events:
        hooks_config["hooks"][event] = [
            {
                "matcher": "*",
                "hooks": [
                    {"type": "command", "command": handler_script}
                ]
            }
        ]

    return hooks_config


def generate_hooks_config_with_handler(
    task_id: int,
    handler_path: str,
    chorus_url: Optional[str] = None,
) -> dict:
    """Generate hooks config using an external handler script.

    This is an alternative to the inline Python command, using a
    dedicated handler script for better error handling.

    Args:
        task_id: The task ID to associate with hook events.
        handler_path: Path to the hook handler script.
        chorus_url: Override the Chorus API URL (for testing).

    Returns:
        Dict containing the hooks configuration.
    """
    url = chorus_url or get_chorus_url()

    # Handler script receives JSON via stdin, task_id and url as env vars
    command = f"CHORUS_URL={url} CHORUS_TASK_ID={task_id} python {handler_path}"

    # Events that don't need a matcher - use simple format
    no_matcher_events = ["SessionStart", "Stop", "SessionEnd"]
    # Events that need a matcher (use "*" for all tools) - use nested format
    matcher_events = ["PermissionRequest", "PostToolUse"]

    hooks_config: dict = {"hooks": {}}

    for event in no_matcher_events:
        hooks_config["hooks"][event] = [
            {"type": "command", "command": command}
        ]

    for event in matcher_events:
        hooks_config["hooks"][event] = [
            {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
        ]

    return hooks_config


def ensure_hooks_config(chorus_url: Optional[str] = None) -> Path:
    """Ensure hooks configuration exists in the shared config directory.

    Creates .claude/settings.json in /tmp/chorus/hooks/ if it doesn't exist.
    Since all sessions share the same config, this is idempotent.

    Args:
        chorus_url: Override the Chorus API URL (for testing).

    Returns:
        Path to the config directory (for CLAUDE_CONFIG_DIR).
    """
    config_dir = get_hooks_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    settings_path = config_dir / "settings.json"

    # Only write if it doesn't exist (idempotent)
    if not settings_path.exists():
        hooks_config = generate_hooks_config(chorus_url)
        settings_path.write_text(json.dumps(hooks_config, indent=2))

    return config_dir


def clear_hooks_config() -> None:
    """Remove the shared hooks config directory.

    This cleans up /tmp/chorus/hooks/.claude/ - typically only called
    during cleanup or testing.
    """
    config_dir = get_hooks_config_dir()

    if config_dir.exists():
        shutil.rmtree(config_dir)


class HooksService:
    """Service for managing Claude Code hooks integration.

    Handles:
    - Generating hooks configuration
    - Ensuring hooks settings exist in shared directory
    - Parsing hook payloads

    Hooks are written to /tmp/chorus/hooks/.claude/ - a shared location
    for all Claude sessions, avoiding pollution of the hosted project.
    """

    def __init__(self, chorus_url: Optional[str] = None):
        """Initialize the hooks service.

        Args:
            chorus_url: Override the Chorus API URL.
        """
        self.chorus_url = chorus_url

    def ensure_hooks(self) -> Path:
        """Ensure hooks configuration exists in the shared directory.

        This is idempotent - safe to call multiple times.

        Returns:
            Path to the config directory (for CLAUDE_CONFIG_DIR).
        """
        return ensure_hooks_config(self.chorus_url)

    def get_config_dir(self) -> Path:
        """Get the shared config directory path.

        Returns:
            Path to the config directory.
        """
        return get_hooks_config_dir()

    def get_hooks_config(self) -> dict:
        """Get the hooks configuration.

        Returns:
            Dict containing the hooks configuration.
        """
        return generate_hooks_config(self.chorus_url)
