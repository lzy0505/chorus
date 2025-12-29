# Chorus

A lightweight orchestration system for managing multiple Claude Code sessions working on a single large project.

## Features

- **Task Management**: Create, prioritize, and track tasks with their own tmux processes
- **GitButler Integration**: Each task gets its own stack (virtual branch) with auto-commits
- **Session Resilience**: Restart Claude Code sessions without losing task context
- **Document Management**: View and reference markdown files as project instructions and context
- **Real-time Dashboard**: Web UI with live status updates and permission request handling
- **Desktop Notifications**: OS-level alerts when Claude needs attention

## Requirements

- Python 3.11+
- tmux
- GitButler CLI (`but`) — for stack management and auto-commits
- uv (recommended) or pip

## Quick Start

```bash
# Install dependencies
uv sync

# Start the server with config file
uv run python main.py chorus.toml

# Open dashboard
open http://localhost:8000
```

## Configuration

Chorus uses a TOML configuration file. Create a `chorus.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8000

[database]
url = "sqlite:///orchestrator.db"

[tmux]
session_prefix = "claude"
poll_interval = 1.0

[editor]
command = "vim"

[documents]
patterns = [
    "*.md",
    "docs/**/*.md",
    ".claude/**/*.md",
]

[status.idle]
patterns = ['>\\s*$', 'claude>\\s*$']

[status.waiting]
patterns = ['\\(y/n\\)', 'Allow\\?', 'Continue\\?']
```

The `PROJECT_ROOT` environment variable is still used to specify the target project directory (defaults to cwd). tmux sessions use environment variables as needed for Claude Code.

## Development

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Start dev server
uv run python main.py chorus.toml
```

## Documentation

- `CLAUDE.md` - Development guide
- `design.md` - Full project specification
