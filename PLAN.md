# Implementation Plan

> Reference: See `design.md` for full specification

## Current Phase: Phase 2 - Task API + Monitor (tmux focus) 🔄

### Phase 1: Core Foundation ✅
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions (Task, Document, DocumentReference)
- [x] Database setup
- [x] tmux service wrapper (basic commands)

### Phase 2: Task API + JSON Monitoring ✅

**Completed: Full task lifecycle with JSON-based monitoring**

- [x] `services/tmux.py` - Task-centric tmux operations ✅
- [x] `services/json_parser.py` - Parse `stream-json` output ✅
- [x] `services/monitor.py` - JSON event monitoring ✅
- [x] `services/gitbutler.py` - GitButler CLI integration ✅
- [x] `api/tasks.py` - Task lifecycle endpoints ✅
- [x] `api/events.py` - SSE endpoint ✅
- [x] JSON session resumption with `--resume` ✅

### Phase 3: Dashboard ✅
- [x] `templates/base.html` - Base layout with htmx/SSE ✅
- [x] `templates/dashboard.html` - Main task-centric dashboard ✅
- [x] `templates/partials/` - Task list, detail, item ✅
- [x] `api/dashboard.py` - HTML partial routes ✅
- [x] `static/style.css` - Dark theme styling ✅

### Phase 4: Document API (Future)
- [ ] `services/documents.py` - Document manager with file discovery
- [ ] `api/documents.py` - Document endpoints
- [ ] Document reference endpoints for task context

### Phase 5: Polish & Reliability ✅
- [x] Error handling (2025-12-30)
  - [x] tmux session not found
  - [x] Claude crash detection
  - [x] GitButler failures
- [x] Edge cases (2025-12-30)
  - [x] Task tmux dies unexpectedly
  - [x] Claude hangs (no output)
  - [x] Branch conflicts
- [x] Comprehensive logging for debugging (2025-12-30)
  - [x] Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - [x] Subprocess command logging (tmux, GitButler CLI, ttyd)
  - [x] API request logging
  - [x] Logging utilities module (`services/logging_utils.py`)
  - [x] Documentation updates
- [ ] Desktop notifications (`services/notifier.py`)
- [ ] Manual testing checklist

## Notes

### Logging Implementation (2025-12-30)

Added comprehensive logging system for debugging external tool interactions:

**Components:**
- `services/logging_utils.py` - Logging utility functions
  - `log_subprocess_call()` - Logs external commands with output
  - `log_api_request()` - Logs HTTP requests
  - `configure_logging()` - Application-wide logging setup
- Configuration via TOML (`logging.level`, `log_subprocess`, `log_api_requests`)
- Applied to all services: tmux, gitbutler, ttyd
- Applied to API endpoints: tasks, hooks, events

**Benefits:**
- Easy debugging of tmux/GitButler command failures
- Detailed visibility into external tool interactions
- Configurable verbosity (DEBUG for troubleshooting, INFO for production)
- Automatic output truncation prevents log spam

**Usage:**
Set `level = "DEBUG"` in `chorus.toml` to see full subprocess execution details when troubleshooting.

### Architecture Decision: Hooks over Polling (2025-12-29)
Changed from terminal polling to Claude Code hooks for status detection:
- **Before**: Poll tmux output every 1s, regex pattern matching for status
- **After**: Claude Code hooks fire events, POST to Chorus API instantly

Benefits:
- Instant status updates (no 1s polling delay)
- Deterministic events (no fragile pattern matching)
- Lower resource usage
- Access to session metadata (transcript_path, session_id)

### Architecture Decision: Shared Hooks Config (2025-12-30)
Changed from per-task hooks to shared project-level hooks:
- **Before**: Each task had its own `/tmp/chorus/task-{id}/.claude/settings.json`
- **After**: All sessions share `/tmp/chorus/hooks/.claude/settings.json`

Key insight: Hooks config is task-agnostic — it just forwards events to the Chorus API with `session_id`. The API looks up tasks by `session_id`, not by config location.

Benefits:
- Simpler: Single config for all sessions
- Idempotent: `ensure_hooks()` only writes if missing
- No cleanup needed: Task completion doesn't delete shared config
- Same isolation: Still outside project directory (`/tmp/chorus/hooks/`)

### Architecture Decision: Task-Centric (2025-12-29)
Changed from session-centric to task-centric design:
- **Before**: Session (tmux) was primary, Task was assigned to Session
- **After**: Task is primary, each Task has its own tmux + GitButler stack

Key insight: Claude sessions are ephemeral (can hang, lose context) but the Task and its tmux persist. This allows restarting Claude without losing task progress.

### GitButler Integration
Using GitButler CLI (`but`):
- `but branch new {name} -j` - Create a new stack for a task
- `but commit -c {stack}` - Commit to specific stack
- `but status -j` - Get workspace status (JSON)
- `but branch show {stack} -j` - Get commits in a stack
- `but branch delete {stack} --force` - Delete a stack

**Per-Task Stack Assignment (Chorus-managed):**
Chorus tracks `task.stack_name` in the database. When a file edit occurs:
1. PostToolUse hook notifies Chorus (`/api/hooks/tooluse`)
2. Chorus looks up task by `session_id` → gets `stack_name`
3. Chorus runs `but commit -c {stack_name}`

```
tmux-1 (task 1): Claude edits → Chorus → but commit -c task-1-auth
tmux-2 (task 2): Claude edits → Chorus → but commit -c task-2-api
```

**Task Lifecycle:**
```
Start:  but branch new → store stack_name in DB → start Claude
Complete: kill tmux
Fail:   optionally but branch delete → kill tmux
```

### Removed
- `Session` model (replaced by task.tmux_session field)
- `api/sessions.py` (session management now part of task API)
- Separate session/task relationship
