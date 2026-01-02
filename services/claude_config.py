"""Service for managing per-task Claude Code configuration.

This service creates isolated Claude config directories for each task,
ensuring that hooks and settings don't pollute the global ~/.claude config.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from uuid import UUID

from services.logging_utils import get_logger

logger = get_logger(__name__)


def get_task_config_dir(task_id: UUID) -> Path:
    """Get the Claude config directory path for a task.

    Args:
        task_id: The task UUID

    Returns:
        Path to the task's Claude config directory
    """
    return Path(f"/tmp/chorus/config/task-{task_id}")


def get_task_settings_file(task_id: UUID) -> Path:
    """Get the Claude settings.json path for a task.

    Args:
        task_id: The task UUID

    Returns:
        Path to the task's settings.json file
    """
    return get_task_config_dir(task_id) / ".claude" / "settings.json"


def create_task_claude_config(task_id: UUID, permission_policy: Optional[Dict[str, Any]] = None) -> Path:
    """Create a task-specific Claude configuration directory.

    This creates:
    - /tmp/chorus/config/task-{uuid}/.claude/settings.json

    The settings.json includes:
    - PermissionRequest hook pointing to the shared permission-handler.py
    - Task-specific configuration

    Args:
        task_id: The task UUID
        permission_policy: Optional permission policy dict (stored in DB, used by handler)

    Returns:
        Path to the config directory
    """
    config_dir = get_task_config_dir(task_id)
    claude_dir = config_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Create settings.json with PermissionRequest hook
    settings = {
        "hooks": {
            "PermissionRequest": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/tmp/chorus/hooks/permission-handler.py",
                            "timeout": 10
                        }
                    ]
                }
            ]
        }
    }

    settings_file = claude_dir / "settings.json"
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)

    logger.info(f"Created task-specific Claude config at {config_dir}")
    logger.debug(f"Settings: {settings}")

    return config_dir


def cleanup_task_claude_config(task_id: UUID) -> None:
    """Remove a task's Claude configuration directory.

    Args:
        task_id: The task UUID
    """
    config_dir = get_task_config_dir(task_id)

    if config_dir.exists():
        import shutil
        shutil.rmtree(config_dir)
        logger.info(f"Removed task-specific Claude config at {config_dir}")


def get_default_permission_policy() -> Dict[str, Any]:
    """Get the default permission policy for new tasks.

    Returns:
        Default permission policy dict
    """
    return {
        "allowed_tools": [
            "Read",
            "Edit",
            "Write",
            "Grep",
            "Glob",
            "LSP",
            "Bash"
        ],
        "prompt_tools": [
            "Write",
            "Edit"
        ],
        "bash_patterns": {
            "allow": [
                "^git status",
                "^git diff",
                "^git log",
                "^git add",
                "^npm test",
                "^npm run test",
                "^pytest",
                "^ls",
                "^pwd",
                "^cat .*\\.(md|txt|json|yaml|yml)",
            ],
            "deny": [
                "rm -rf /",
                "sudo",
                "DROP TABLE",
                "DELETE FROM",
            ]
        },
        "file_patterns": {
            "allow": [
                "*.py",
                "*.js",
                "*.ts",
                "*.tsx",
                "*.md",
                "*.json",
                "*.yaml",
                "*.yml",
                "*.txt",
            ],
            "deny": [
                ".env",
                ".git/*",
                "secrets.json",
                "*.key",
                "*.pem",
                "credentials*",
            ]
        },
        "auto_approve": False  # Prompt for commands not explicitly allowed
    }


def get_permission_profile(profile_name: str) -> Dict[str, Any]:
    """Get a predefined permission profile.

    Args:
        profile_name: Name of the profile (read_only, safe_edit, full_dev, etc.)

    Returns:
        Permission policy dict
    """
    profiles = {
        "read_only": {
            "allowed_tools": ["Read", "Grep", "Glob", "LSP"],
            "bash_patterns": {
                "allow": ["^ls", "^pwd", "^cat"],
                "deny": [".*"]
            },
            "file_patterns": {
                "allow": ["*"],
                "deny": []
            },
            "auto_approve": True
        },
        "safe_edit": {
            "allowed_tools": ["Read", "Edit", "Write", "Grep", "Glob", "LSP"],
            "prompt_tools": ["Write", "Edit"],
            "bash_patterns": {
                "allow": ["^git status", "^git diff", "^git log"],
                "deny": [".*"]  # Block all other bash
            },
            "file_patterns": {
                "allow": ["*.py", "*.js", "*.ts", "*.md", "*.json"],
                "deny": [".env", ".git/*", "*.key"]
            },
            "auto_approve": True
        },
        "full_dev": get_default_permission_policy(),
        "git_only": {
            "allowed_tools": ["Read", "Grep", "Glob"],
            "bash_patterns": {
                "allow": ["^git "],
                "deny": []
            },
            "file_patterns": {
                "allow": ["*"],
                "deny": [".env", "*.key"]
            },
            "auto_approve": True
        },
    }

    return profiles.get(profile_name, get_default_permission_policy())
