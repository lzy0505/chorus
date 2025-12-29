# Chorus

Task-centric orchestration for multiple Claude Code sessions. See `design.md` for full specification.

## GitButler Workflow (MANDATORY)

**NEVER use these git commands:**
- `git commit`, `git push`, `git stash`, `git rebase`, `git merge`, `git reset`, `git cherry-pick`

**Allowed (read-only):**
- `git status`, `git diff`, `git log`, `git add`

Chorus manages GitButler commits centrally. Direct git commands bypass the system and cause conflicts.

**GitButler CLI (`but`):**
- `but status` — View workspace with all stacks
- `but branch new <name>` — Create a new stack
- `but branch delete <stack> --force` — Delete a stack
- `but commit -c <stack>` — Commit to specific stack

**Per-Task Stack Assignment:** Chorus tracks `task.stack_name` in DB. After file edits, Chorus commits to the correct stack via `but commit -c`. Concurrent tasks are fully supported.

**Terminology:** GitButler uses "stacks" (virtual branches) that run in parallel. Multiple tasks can have concurrent stacks in the same workspace.

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
