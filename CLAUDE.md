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
├── services/            # Business logic (tmux, monitor, json_parser, gitbutler, notifier)
├── templates/           # Jinja2 templates
└── static/              # CSS and assets
```

## Architecture

Chorus uses **JSON-based monitoring** for Claude Code sessions. Set `monitoring.use_json_mode = true` in `chorus.toml` (recommended).

### JSON Monitoring (Current Architecture)

```
┌─────────────────────────────────────────────────────────────┐
│ services/tmux.py                                             │
│ └─ start_claude() → `claude --output-format stream-json`    │
│ └─ capture_json_events() → Capture JSON from tmux           │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/json_monitor.py (JSON Monitor)                     │
│ └─ poll_json_events() → Parse stream-json from tmux         │
│ └─ handle_tool_use() → Detect file edits                    │
│ └─ handle_tool_result() → Trigger GitButler commit          │
│ └─ handle_result() → Extract session_id for resumption      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/gitbutler.py                                        │
│ └─ commit_to_stack(stack_name)                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Features:**
- **Deterministic event detection** — Parse structured JSON events from Claude
- **Session resumption** — Extract `session_id` from JSON for `--resume`
- **Real-time status updates** — Event-driven architecture
- **Permission handling** — Non-interactive permission management with `--allowedTools`
- **Multi-step task support** — Resume sessions with `-p --resume` for sequential work
- **More reliable** — No regex pattern matching, structured data

**Critical Concepts:**

1. **`-p` Flag (SDK Mode)**: Claude runs non-interactively, processes prompt, exits atomically
   - Task completion ≠ Process termination
   - Use `--resume` to continue multi-step tasks
   - See `docs/TERMINATION_HANDLING.md` for lifecycle patterns

2. **Permission Management**: Without permission flags, `-p` blocks indefinitely
   - Use `--allowedTools` to pre-approve tools
   - Use `--permission-mode acceptEdits` for safe file editing
   - See `docs/PERMISSION_HANDLING.md` for configuration strategies

3. **Status Tracking**: Derive granular status from JSON events
   - `idle`, `thinking`, `reading`, `editing`, `running`, `waiting`, `stopped`
   - See `docs/STATUS_TRACKING.md` for implementation recommendations

**Documentation:**
- `docs/JSON_EVENTS.md` - Complete JSON event format specification
- `docs/TERMINATION_HANDLING.md` - Process termination and task continuation patterns
- `docs/PERMISSION_HANDLING.md` - Permission configuration for non-interactive sessions
- `docs/STATUS_TRACKING.md` - Granular status tracking from events

**Important: Two Different "Hooks" Systems**

Chorus uses the term "hooks" in two different contexts:

1. **Claude Code hooks** (DEPRECATED) — Callbacks like SessionStart, ToolUse that Claude Code can trigger. Replaced by JSON monitoring.
2. **GitButler hooks** (IN PROGRESS) — CLI commands (`but claude pre-tool/post-tool/stop`) for stack isolation. Methods implemented but not yet integrated.

### Legacy Claude Code Hook Mode

Set `monitoring.use_json_mode = false` for compatibility.

Uses Claude Code's SessionStart/ToolUse callbacks + status polling. Legacy files (`services/hooks.py`, `services/status_detector.py`) still exist for this mode but JSON mode is recommended.

## Development

```bash
uv run python main.py                   # Start server (http://localhost:8000)
uv run pytest                           # Run tests
uv run pytest -m "not integration"      # Skip tmux tests
uv run pytest --cov                     # Coverage report
```

## Documentation Updates

For any non-bug-fix changes (new features, refactors, architecture changes), update the relevant documentation:

| Change Type | Update |
|-------------|--------|
| New feature / API | `DESIGN.md` (spec), `PLAN.md` (checklist) |
| Architecture change | `DESIGN.md` (details), `PLAN.md` (add decision note) |
| Refactor | `PLAN.md` (note if significant) |
| Completed work | `TODO.md` (mark done), `PLAN.md` (check off items) |

Keep docs proportional to the change — major changes need thorough updates, minor ones just a note.

## Key Documentation

| File | Content |
|------|---------|
| `design.md` | Architecture, data models, API spec, implementation details |
| `PLAN.md` | Current phase, task breakdown, notes |
| `README.md` | Quick start, configuration |
| `docs/JSON_EVENTS.md` | Claude Code JSON event format specification (10 event types) |
| `docs/TERMINATION_HANDLING.md` | Process termination, `-p` flag behavior, session resumption |
| `docs/PERMISSION_HANDLING.md` | Permission configuration, `--allowedTools`, profiles |
| `docs/STATUS_TRACKING.md` | Granular status tracking, activity context, UI design |
