# Claude Session Orchestrator - Development Guide

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
- Mark items with ✅ when phase/task is complete
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

This is a lightweight orchestration system for managing multiple Claude Code sessions working on a single large project. The full specification is in `design.md`.

## Tech Stack

- **Backend**: FastAPI + SQLModel + SQLite
- **Frontend**: htmx + Jinja2 templates + SSE for real-time updates
- **Session Management**: tmux for process isolation
- **Notifications**: OS-native (osascript on macOS, notify-send on Linux)

## Development Workflow

- Run `uv run python main.py` to start the dev server
- API docs available at http://localhost:8000/docs
- After code changes, run gitbutler mcp update_branches (do NOT use git commit)

## Project Structure

```
chorus/
├── main.py              # FastAPI entry point
├── config.py            # Configuration settings
├── models.py            # SQLModel definitions
├── database.py          # Database setup
├── api/                 # API routers
│   ├── sessions.py      # Session endpoints
│   ├── tasks.py         # Task endpoints
│   ├── documents.py     # Document endpoints
│   └── events.py        # SSE stream
├── services/            # Business logic
│   ├── tmux.py          # Tmux wrapper
│   ├── monitor.py       # Session polling
│   ├── detector.py      # Status detection
│   ├── documents.py     # Document manager
│   └── notifier.py      # Desktop notifications
├── templates/           # Jinja2 templates
│   ├── base.html
│   ├── dashboard.html
│   └── partials/
└── static/              # CSS and assets
```

## Implementation Phases

Follow phases from `design.md`:
1. Core Foundation (config, models, tmux wrapper)
2. Session API + Monitor (status detection, SSE)
3. Task API (CRUD, assignment)
4. Document API (discovery, references)
5. Dashboard (htmx UI)
6. Polish (error handling, edge cases)

## Key Patterns

### Status Detection
```python
# Session statuses: idle, busy, waiting, stopped
# Check terminal output for patterns:
# - ">" or "claude>" at end = idle
# - "(y/n)" or "Allow?" = waiting
# - Otherwise = busy
```

### SSE Events
```
event: session_status   # Session status changed
event: task_update      # Task status changed
event: document_change  # Document modified
```

### Task Assignment
When assigning a task:
1. Fetch task and its DocumentReferences
2. Read line ranges from referenced documents
3. Build prompt with context
4. Send via `tmux send-keys`

## Conventions

- Use async/await for I/O operations
- Keep API endpoints thin, logic in services/
- Return Pydantic models from API endpoints
- Use dependency injection for database sessions
- Emit SSE events for any state changes

## Testing

### Running Tests
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Run specific test file
uv run pytest tests/test_models.py

# Run tests matching a pattern
uv run pytest -k "session"

# Skip integration tests (require tmux)
uv run pytest -m "not integration"
```

### Test Structure
- `tests/conftest.py` - Fixtures (db, client, temp dirs)
- `tests/test_models.py` - SQLModel tests
- `tests/test_services.py` - Service layer tests (mocked)
- `tests/test_api.py` - API endpoint tests

### Writing Tests
- Use `db` fixture for database tests
- Use `client` fixture for API tests
- Mock external calls (tmux, filesystem) in service tests
- Mark slow/integration tests with `@pytest.mark.slow` or `@pytest.mark.integration`

### Manual Testing
Run checklist from `design.md`:
- Create/monitor/kill sessions
- Create/assign/complete tasks
- Discover/view/reference documents
- Real-time dashboard updates

## Environment Variables

```bash
PROJECT_ROOT=/path/to/project  # Required
EDITOR=nvim                    # Optional
PORT=8000                      # Optional
```
