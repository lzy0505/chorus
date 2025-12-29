# Chorus — Task-Centric Claude Session Orchestrator

## GitButler Workflow (MANDATORY)

**CRITICAL: This workflow MUST be followed for this project.**

### After ANY code changes:
1. GitButler hooks automatically sync changes via `but claude post-tool`
2. GitButler manages all commits and branches

### NEVER use these git commands directly:
- `git commit` - BLOCKED
- `git push` - BLOCKED
- `git stash` - BLOCKED
- `git rebase` - BLOCKED
- `git merge` - BLOCKED
- `git reset` - BLOCKED
- `git cherry-pick` - BLOCKED

### Allowed git commands (read-only):
- `git status` - OK
- `git diff` - OK
- `git log` - OK
- `git add` - OK (staging only)

### Why GitButler?
GitButler provides virtual branches and better commit management. Direct git commands bypass this system and can cause conflicts.

---

## Task Tracking (IMPORTANT)

**Always maintain these files when working on tasks:**

### TODO.md
- Check `TODO.md` at the start of each session to see current tasks
- Move tasks between sections as you work:
  - `In Progress` → what you're actively working on
  - `Up Next` → priority tasks
  - `Completed` → finished tasks (add `[x]` prefix)
- Update after completing any task

### PLAN.md
- Shows implementation phases and progress
- Mark items with checkmark when phase/task is complete
- Mark current phase with 🔄
- Add notes for decisions, blockers, or context

### Workflow
1. **Start of session**: Read `TODO.md` and `PLAN.md` to understand current state
2. **Pick a task**: Move it to "In Progress" in TODO.md
3. **Complete task**: Move to "Completed", update PLAN.md if needed
4. **End of session**: Ensure both files reflect current state

The TodoWrite tool syncs with TODO.md via hooks automatically.

---

## Project Overview

Chorus is a lightweight orchestration system for managing multiple Claude Code tasks working on a single large project. The full specification is in `design.md`.

### Core Concept

```
Task = tmux process + GitButler branch + ephemeral Claude sessions
```

- **Task** is the primary entity — represents a unit of work
- **tmux process** persists for the task's lifetime — provides isolation
- **Claude sessions** are ephemeral — can be restarted within the same tmux
- **GitButler branch** tracks all changes — commits automatically on task completion

## Tech Stack

- **Backend**: FastAPI + SQLModel + SQLite
- **Frontend**: htmx + Jinja2 templates + SSE for real-time updates
- **Process Isolation**: tmux (one per task)
- **Git Integration**: GitButler MCP for branch/commit management
- **Notifications**: OS-native (osascript on macOS, notify-send on Linux)

## Development Workflow

- Run `uv run python main.py` to start the dev server
- API docs available at http://localhost:8000/docs
- GitButler hooks automatically sync changes (do NOT use git commit directly)

## Project Structure

```
chorus/
├── main.py              # FastAPI entry point
├── config.py            # Configuration settings
├── models.py            # SQLModel definitions (Task, Document, DocumentReference)
├── database.py          # Database setup
├── api/                 # API routers
│   ├── tasks.py         # Task lifecycle endpoints
│   ├── documents.py     # Document endpoints
│   └── events.py        # SSE stream
├── services/            # Business logic
│   ├── tmux.py          # Tmux wrapper
│   ├── monitor.py       # Task polling loop
│   ├── detector.py      # Claude status detection
│   ├── gitbutler.py     # GitButler MCP integration
│   ├── documents.py     # Document manager
│   └── notifier.py      # Desktop notifications
├── templates/           # Jinja2 templates
│   ├── base.html
│   ├── dashboard.html
│   └── partials/
└── static/              # CSS and assets
```

## Key Architecture Patterns

### Task Lifecycle

```
pending → running ↔ waiting → completed
                          ↘ failed
```

1. **Create Task** (`pending`) — user creates task with description
2. **Start Task** → creates GitButler branch, spawns tmux, launches Claude
3. **Monitor** → poll tmux output, detect Claude status
4. **Restart Claude** → if session hangs, restart within same tmux
5. **Complete Task** → generate commit message, commit via GitButler, kill tmux

### Claude Session Management

Claude sessions within a task's tmux are ephemeral:
- Can hang, lose context, or crash
- Restart by killing Claude (Ctrl+C) and relaunching
- Track restart count per task
- Optionally resend context on restart

### tmux Commands

```bash
# Create session for task
tmux new-session -d -s task-{id} -c {project_root}

# Start Claude
tmux send-keys -t task-{id} "claude" Enter

# Capture output (for status detection)
tmux capture-pane -t task-{id} -p -S -100

# Kill Claude (Ctrl+C)
tmux send-keys -t task-{id} C-c

# Kill session
tmux kill-session -t task-{id}
```

### Status Detection

```python
# Claude at prompt, waiting for input
IDLE: r">\s*$" or r"claude>\s*$"

# Claude asking for permission
WAITING: r"\(y/n\)", r"Allow\?", r"Do you want to"

# Otherwise → BUSY
```

### GitButler Integration

GitButler hooks are configured in `.claude/settings.local.json`:
- `but claude pre-tool` - runs before Edit/Write operations
- `but claude post-tool` - syncs changes after Edit/Write operations
- `but claude stop` - runs when Claude session stops

## Implementation Phases

See `PLAN.md` for current progress. Priority is on tmux/task management:

1. **Phase 1**: Core Foundation (DONE)
2. **Phase 2**: Task API + Monitor (CURRENT - tmux focus)
3. **Phase 3**: Document API
4. **Phase 4**: Dashboard
5. **Phase 5**: Polish

## Testing

### Running Tests
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Skip integration tests (require tmux)
uv run pytest -m "not integration"
```

### Test Structure
- `tests/conftest.py` - Fixtures
- `tests/test_models.py` - SQLModel tests
- `tests/test_services.py` - Service layer tests
- `tests/test_api.py` - API endpoint tests

## Environment Variables

```bash
PROJECT_ROOT=/path/to/project  # Required
EDITOR=nvim                    # Optional
PORT=8000                      # Optional
POLL_INTERVAL=1.0              # Status polling interval
```
