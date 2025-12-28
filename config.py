"""Configuration settings for Claude Session Orchestrator."""

import os
from pathlib import Path

# Project being managed
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", os.getcwd()))

# tmux settings
SESSION_PREFIX = os.environ.get("SESSION_PREFIX", "claude")

# Polling interval for session monitoring (seconds)
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///orchestrator.db")

# Server settings
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# External editor
EDITOR = os.environ.get("EDITOR", "vim")

# Document discovery patterns
DOCUMENT_PATTERNS = [
    "*.md",
    "docs/**/*.md",
    ".claude/**/*.md",
    "plans/**/*.md",
    "specs/**/*.md",
]

# Status detection patterns
STATUS_PATTERNS = {
    "idle": [
        r">\s*$",
        r"claude>\s*$",
    ],
    "waiting": [
        r"\(y/n\)",
        r"Allow\?",
        r"Do you want to",
        r"Proceed\?",
        r"Press Enter",
        r"Continue\?",
    ],
}
