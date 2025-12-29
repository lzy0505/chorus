"""Claude Code hooks integration for real-time status updates.

This module generates hook configurations and handles hook events from Claude Code.
Instead of polling terminal output, we use Claude's native hooks for deterministic
status detection.

Hook events used:
- SessionStart: Claude launches → map session to task
- Stop: Claude finishes responding → idle status
- PermissionRequest: Permission dialog shown → waiting status
- SessionEnd: Claude exits → stopped status
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import HOST, PORT


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
    return f"http://{HOST}:{PORT}"


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

    return {
        "hooks": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": handler_script,
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": handler_script,
                }
            ],
            "PermissionRequest": [
                {
                    "type": "command",
                    "command": handler_script,
                }
            ],
            "SessionEnd": [
                {
                    "type": "command",
                    "command": handler_script,
                }
            ],
            "PostToolUse": [
                {
                    "type": "command",
                    "command": handler_script,
                }
            ],
        }
    }


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

    return {
        "hooks": {
            "SessionStart": [{"type": "command", "command": command}],
            "Stop": [{"type": "command", "command": command}],
            "PermissionRequest": [{"type": "command", "command": command}],
            "SessionEnd": [{"type": "command", "command": command}],
            "PostToolUse": [{"type": "command", "command": command}],
        }
    }


def write_hooks_config(
    project_root: Path,
    task_id: int,
    chorus_url: Optional[str] = None,
) -> Path:
    """Write hooks configuration to .claude/settings.json.

    Creates or updates the .claude/settings.json file in the project
    with hooks that POST to the Chorus API.

    Args:
        project_root: Path to the project root directory.
        task_id: The task ID for this session.
        chorus_url: Override the Chorus API URL (for testing).

    Returns:
        Path to the written settings file.
    """
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_path = claude_dir / "settings.json"

    # Load existing settings if present
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            existing = {}

    # Generate and merge hooks config
    hooks_config = generate_hooks_config(task_id, chorus_url)
    existing.update(hooks_config)

    # Write back
    settings_path.write_text(json.dumps(existing, indent=2))

    return settings_path


def clear_hooks_config(project_root: Path) -> None:
    """Remove hooks configuration from .claude/settings.json.

    Removes the hooks section while preserving other settings.

    Args:
        project_root: Path to the project root directory.
    """
    settings_path = project_root / ".claude" / "settings.json"

    if not settings_path.exists():
        return

    try:
        settings = json.loads(settings_path.read_text())
        if "hooks" in settings:
            del settings["hooks"]
            settings_path.write_text(json.dumps(settings, indent=2))
    except json.JSONDecodeError:
        pass


class HooksService:
    """Service for managing Claude Code hooks integration.

    Handles:
    - Generating hooks configuration for tasks
    - Writing/clearing hooks settings
    - Parsing hook payloads
    """

    def __init__(self, project_root: Optional[Path] = None, chorus_url: Optional[str] = None):
        """Initialize the hooks service.

        Args:
            project_root: Project root directory. Defaults to config PROJECT_ROOT.
            chorus_url: Override the Chorus API URL.
        """
        from config import PROJECT_ROOT
        self.project_root = project_root or PROJECT_ROOT
        self.chorus_url = chorus_url

    def setup_hooks(self, task_id: int) -> Path:
        """Set up hooks for a task.

        Args:
            task_id: The task ID.

        Returns:
            Path to the settings file.
        """
        return write_hooks_config(self.project_root, task_id, self.chorus_url)

    def teardown_hooks(self) -> None:
        """Remove hooks configuration."""
        clear_hooks_config(self.project_root)

    def get_hooks_config(self, task_id: int) -> dict:
        """Get the hooks configuration for a task.

        Args:
            task_id: The task ID.

        Returns:
            Dict containing the hooks configuration.
        """
        return generate_hooks_config(task_id, self.chorus_url)
