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
uv pip install -r requirements.txt

# Set project root (the project you want Claude to work on)
export PROJECT_ROOT=/path/to/your/project

# Start the server
uv run python main.py

# Open dashboard
open http://localhost:8000
```

## Development

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Start dev server with reload
uv run python main.py
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_ROOT` | cwd | Project directory to manage |
| `PORT` | 8000 | Server port |
| `EDITOR` | vim | External editor for documents |
| `SESSION_PREFIX` | claude | Prefix for tmux sessions |

## Documentation

- `CLAUDE.md` - Development guide
- `design.md` - Full project specification
