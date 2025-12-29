# Chorus

Task-centric orchestration for multiple Claude Code sessions. See `design.md` for full specification.

## GitButler Workflow (MANDATORY)

**NEVER use these git commands:**
- `git commit`, `git push`, `git stash`, `git rebase`, `git merge`, `git reset`, `git cherry-pick`

**Allowed (read-only):**
- `git status`, `git diff`, `git log`, `git add`

GitButler hooks handle all commits automatically. Direct git commands bypass the system and cause conflicts.

---

## Task Tracking

Always maintain these files:

| File | Purpose |
|------|---------|
| `TODO.md` | Current tasks — move between In Progress/Up Next/Completed |
| `PLAN.md` | Implementation phases — mark progress with ✅ and 🔄 |

**Workflow:** Check both files at session start → Pick a task → Update as you work → Ensure files reflect current state at session end.

TodoWrite tool syncs with TODO.md automatically.

---

## Project Structure

```
chorus/
├── main.py              # FastAPI entry point
├── config.py            # Configuration
├── models.py            # SQLModel definitions
├── database.py          # Database setup
├── api/                 # API routers (tasks, documents, events)
├── services/            # Business logic (tmux, monitor, detector, gitbutler, notifier)
├── templates/           # Jinja2 templates
└── static/              # CSS and assets
```

## Development

```bash
uv run python main.py                   # Start server (http://localhost:8000)
uv run pytest                           # Run tests
uv run pytest -m "not integration"      # Skip tmux tests
uv run pytest --cov                     # Coverage report
```

## Key Documentation

| File | Content |
|------|---------|
| `design.md` | Architecture, data models, API spec, implementation details |
| `PLAN.md` | Current phase, task breakdown, notes |
| `README.md` | Quick start, configuration |
