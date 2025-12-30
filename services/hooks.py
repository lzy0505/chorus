"""Claude Code hooks integration for real-time status updates.

This module generates hook configurations and handles hook events from Claude Code.
Instead of polling terminal output, we use Claude's native hooks for deterministic
status detection.

Hook events used:
- SessionStart: Claude launches → map session to task
- Stop: Claude finishes responding → idle status
- PermissionRequest: Permission dialog shown → waiting status
- SessionEnd: Claude exits → stopped status

Isolation with Global Config Inheritance:
Hooks are written to /tmp/chorus/hooks/.claude/ to avoid polluting
the hosted project's working directory. The isolated config is created by:
1. Copying all files from ~/.claude/ (settings, projects, etc.)
2. Copying ~/.claude.json (credentials with oauthAccount) into the config dir
3. Deep merging Chorus-specific hooks into settings.json

This ensures each tmux session has access to:
- Login credentials (no re-authentication needed for spawned sessions)
- User's global settings (permissions, model preferences, allowed tools)
- Chorus-specific hooks for task tracking

All without polluting the global config. Claude Code is launched with
CLAUDE_CONFIG_DIR pointing to this shared location.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from config import get_config


def get_global_config_dir() -> Path:
    """Get the path to the global Claude config directory.

    Returns:
        Path to ~/.claude/
    """
    return Path.home() / ".claude"


def get_global_credentials_path() -> Path:
    """Get the path to the global Claude credentials file.

    Claude stores credentials in ~/.claude.json (at home root, not inside .claude/).

    Returns:
        Path to ~/.claude.json
    """
    return Path.home() / ".claude.json"


def get_global_config_path() -> Path:
    """Get the path to the global Claude config.

    Returns:
        Path to ~/.claude/settings.json
    """
    return get_global_config_dir() / "settings.json"


def deep_merge_hooks(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two hook configurations.

    Merges the overlay config into the base config, preserving both.
    For hooks arrays, the overlay hooks are appended to existing ones.

    Args:
        base: The base configuration (e.g., from global config).
        overlay: The overlay configuration (e.g., Chorus hooks).

    Returns:
        Merged configuration with all settings from both.
    """
    result = base.copy()

    for key, value in overlay.items():
        if key not in result:
            result[key] = value
        elif key == "hooks" and isinstance(value, dict) and isinstance(result[key], dict):
            # Merge hooks specially - append to existing hook arrays
            merged_hooks = result[key].copy()
            for event, hooks_list in value.items():
                if event in merged_hooks:
                    # Append new hooks to existing event hooks
                    merged_hooks[event] = merged_hooks[event] + hooks_list
                else:
                    merged_hooks[event] = hooks_list
            result[key] = merged_hooks
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            # Recursively merge nested dicts
            result[key] = deep_merge_hooks(result[key], value)
        else:
            # Overlay value takes precedence for non-dict values
            result[key] = value

    return result


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


def generate_hooks_config(chorus_url: Optional[str] = None) -> dict:
    """Generate Claude Code hooks configuration.

    This creates the hooks section for .claude/settings.json that will
    POST events to the Chorus API. The config is task-agnostic - the API
    uses session_id from the payload to find the associated task.

    Args:
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

    # All hook events use the nested format with matcher and hooks array.
    # Events like SessionStart/Stop/SessionEnd use empty matcher "" to match all.
    # Events like PermissionRequest/PostToolUse use "*" to match all tools.
    hooks_config: dict = {"hooks": {}}

    # Session lifecycle events - empty matcher matches everything
    for event in ["SessionStart", "Stop", "SessionEnd"]:
        hooks_config["hooks"][event] = [
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": handler_script}]
            }
        ]

    # Tool-related events - "*" matcher matches all tools
    for event in ["PermissionRequest", "PostToolUse"]:
        hooks_config["hooks"][event] = [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": handler_script}]
            }
        ]

    return hooks_config


def generate_hooks_config_with_handler(
    handler_path: str,
    chorus_url: Optional[str] = None,
) -> dict:
    """Generate hooks config using an external handler script.

    This is an alternative to the inline Python command, using a
    dedicated handler script for better error handling.

    Args:
        handler_path: Path to the hook handler script.
        chorus_url: Override the Chorus API URL (for testing).

    Returns:
        Dict containing the hooks configuration.
    """
    url = chorus_url or get_chorus_url()

    # Handler script receives JSON via stdin, url as env var
    command = f"CHORUS_URL={url} python {handler_path}"

    # All hook events use the nested format with matcher and hooks array.
    hooks_config: dict = {"hooks": {}}

    # Session lifecycle events - empty matcher matches everything
    for event in ["SessionStart", "Stop", "SessionEnd"]:
        hooks_config["hooks"][event] = [
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": command}]
            }
        ]

    # Tool-related events - "*" matcher matches all tools
    for event in ["PermissionRequest", "PostToolUse"]:
        hooks_config["hooks"][event] = [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command}]
            }
        ]

    return hooks_config


def ensure_hooks_config(chorus_url: Optional[str] = None, force: bool = False) -> Path:
    """Ensure hooks configuration exists in the shared config directory.

    Creates /tmp/chorus/hooks/.claude/ by:
    1. Copying all files from ~/.claude/ (settings, projects, etc.)
    2. Copying ~/.claude.json (credentials with oauthAccount) into the config dir
    3. Merging Chorus-specific hooks into settings.json

    This ensures tmux sessions have access to:
    - Login credentials (no re-authentication needed)
    - User's global settings (permissions, model preferences, allowed tools)
    - Chorus-specific hooks for task tracking

    All without polluting the global config.

    IMPORTANT: Credentials are ALWAYS refreshed from ~/.claude.json to ensure
    spawned sessions pick up any authentication changes (e.g., after re-login).

    Args:
        chorus_url: Override the Chorus API URL (for testing).
        force: Force regeneration even if config exists.

    Returns:
        Path to the config directory (for CLAUDE_CONFIG_DIR).
    """
    config_dir = get_hooks_config_dir()
    settings_path = config_dir / "settings.json"

    # Always refresh credentials from ~/.claude.json to pick up auth changes
    # This is critical: if user re-authenticates, spawned sessions need new creds
    global_creds = get_global_credentials_path()
    if global_creds.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        target_creds = config_dir / ".claude.json"
        shutil.copy2(global_creds, target_creds)

    # Check if we need to regenerate the full config (settings, hooks, etc.)
    if settings_path.exists() and not force:
        return config_dir

    # Remove existing config dir if forcing regeneration
    if config_dir.exists() and force:
        shutil.rmtree(config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)

    # Copy entire global config directory if it exists
    global_config_dir = get_global_config_dir()
    if global_config_dir.exists():
        shutil.copytree(global_config_dir, config_dir, dirs_exist_ok=True)
    else:
        config_dir.mkdir(parents=True, exist_ok=True)

    # Copy credentials again after copytree (in case it was overwritten)
    if global_creds.exists():
        target_creds = config_dir / ".claude.json"
        shutil.copy2(global_creds, target_creds)

    # Load existing settings (from copied global config) or start fresh
    if settings_path.exists():
        try:
            base_config = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            base_config = {}
    else:
        base_config = {}

    # Generate and merge Chorus hooks
    chorus_hooks = generate_hooks_config(chorus_url)
    merged_config = deep_merge_hooks(base_config, chorus_hooks)

    settings_path.write_text(json.dumps(merged_config, indent=2))

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
    - Ensuring hooks settings exist in shared directory (copied from global + merged)
    - Parsing hook payloads

    Hooks are written to /tmp/chorus/hooks/.claude/ - a shared location
    for all Claude sessions. The config is created by:
    1. Copying all files from ~/.claude/ (settings, projects, etc.)
    2. Copying ~/.claude.json (credentials with oauthAccount) into the config dir
    3. Merging Chorus hooks into settings.json

    This keeps the global config clean while providing full functionality and
    eliminating the need for re-authentication in spawned sessions.
    """

    def __init__(self, chorus_url: Optional[str] = None):
        """Initialize the hooks service.

        Args:
            chorus_url: Override the Chorus API URL.
        """
        self.chorus_url = chorus_url

    def ensure_hooks(self, force: bool = False) -> Path:
        """Ensure hooks configuration exists in the shared directory.

        Merges the user's global Claude config with Chorus hooks.
        This is idempotent - safe to call multiple times.

        Args:
            force: Force regeneration even if config exists (useful if
                   global config changed).

        Returns:
            Path to the config directory (for CLAUDE_CONFIG_DIR).
        """
        return ensure_hooks_config(self.chorus_url, force=force)

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
