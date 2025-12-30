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
- ttyd (optional) — for web-based terminal access
- uv (recommended) or pip
- Claude Code with valid subscription (Pro/Max)

### Installing ttyd (optional)

ttyd provides interactive web terminal access to task sessions:

```bash
# macOS
brew install ttyd

# Linux (Debian/Ubuntu)
apt install ttyd
```

Without ttyd, tasks still work but won't have web terminal access.

### Authentication Setup (Required)

Chorus spawns multiple Claude Code sessions that need authentication. Since OAuth tokens from browser login don't transfer to isolated sessions, you must set up a long-lived token:

```bash
# 1. Generate OAuth token (one-time setup, opens browser)
claude setup-token

# 2. Set the token in your shell profile (~/.zshrc or ~/.bashrc)
export CLAUDE_CODE_OAUTH_TOKEN="<token-from-step-1>"

# 3. Reload your shell or source the profile
source ~/.zshrc
```

Without this, spawned Claude sessions will show "Missing API Key / Run /login".

## Quick Start

```bash
# Install dependencies
uv sync

# Start the server with config file and project path
uv run python main.py chorus.toml /absolute/path/to/project

# Open dashboard
open http://localhost:8000
```

## Configuration

Chorus requires two arguments:
1. **Config file** - TOML file with server settings
2. **Project path** - Absolute path to the project directory to manage

Create a `chorus.toml`:

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

Each Chorus instance manages a single project. tmux sessions use environment variables as needed for Claude Code.

## Development

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Start dev server (from chorus directory, managing itself)
uv run python main.py chorus.toml "$(pwd)"
```

## Documentation

- `CLAUDE.md` - Development guide
- `design.md` - Full project specification
