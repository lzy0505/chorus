# Implementation Plan

> Reference: See `design.md` for full specification

## Current Phase: Phase 2 - Task API + Monitor (tmux focus) 🔄

### Phase 1: Core Foundation ✅
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions (Task, Document, DocumentReference)
- [x] Database setup
- [x] tmux service wrapper (basic commands)

### Phase 2: Task API + Hooks 🔄

**Priority: tmux, hooks, and task lifecycle management**

- [x] Update `services/tmux.py` - Task-centric tmux operations ✅
  - [x] `create_task_session(task_id)` - Create tmux for a task
  - [x] `start_claude(task_id)` - Launch Claude in task's tmux
  - [x] `restart_claude(task_id)` - Kill and relaunch Claude
  - [x] `kill_task_session(task_id)` - Kill task's tmux
  - [x] `capture_output(task_id)` - Get terminal output
  - [x] `send_keys(task_id, text)` - Send input to Claude

- [x] `services/hooks.py` - Claude Code hooks integration ✅
  - [x] `generate_hooks_config(task_id)` - Generate .claude/settings.json for task
  - [x] `HookPayload` dataclass for parsing hook events
  - [x] `HooksService` class for setup/teardown
  - [x] Session-to-task mapping via `claude_session_id`

- [x] `api/hooks.py` - Hook event endpoints ✅
  - [x] `POST /api/hooks/sessionstart` - SessionStart event → map session to task
  - [x] `POST /api/hooks/stop` - Stop event → claude_status = idle
  - [x] `POST /api/hooks/permissionrequest` - PermissionRequest → status = waiting
  - [x] `POST /api/hooks/sessionend` - SessionEnd → claude_status = stopped
  - [x] `POST /api/hooks/notification` - Notification → confirms idle

- [x] `services/gitbutler.py` - GitButler CLI integration ✅
  - [x] `create_stack(name)` - Create stack via `but branch new -j`
  - [x] `commit_to_stack(stack)` - Commit to stack via `but commit -c`
  - [x] `get_status()` - Get workspace status via `but status -j`
  - [x] `delete_stack(stack)` - Delete stack via `but branch delete --force`
  - [x] `get_stack_commits(stack)` - Get commits via `but branch show -j`

- [x] `api/hooks.py` - Add tooluse endpoint ✅
  - [x] `POST /api/hooks/posttooluse` - After file edit, commit to task's stack

- [ ] `api/tasks.py` - Task lifecycle endpoints
  - [ ] `POST /api/tasks` - Create task
  - [ ] `GET /api/tasks` - List tasks
  - [ ] `GET /api/tasks/{id}` - Get task details
  - [ ] `PUT /api/tasks/{id}` - Update task
  - [ ] `POST /api/tasks/{id}/start` - Start task (stack + tmux + Claude)
  - [ ] `POST /api/tasks/{id}/restart-claude` - Restart Claude session
  - [ ] `POST /api/tasks/{id}/send` - Send message to Claude
  - [ ] `POST /api/tasks/{id}/respond` - Respond to permission prompt
  - [ ] `POST /api/tasks/{id}/complete` - Complete task (finalize, GitButler auto-commits)
  - [ ] `POST /api/tasks/{id}/fail` - Mark task as failed, optionally delete stack
  - [ ] `DELETE /api/tasks/{id}` - Delete pending/failed task

- [ ] `api/events.py` - SSE endpoint
  - [ ] Event queue
  - [ ] `task_status` events
  - [ ] `claude_status` events

### Phase 3: Document API
- [ ] `services/documents.py` - Document manager
  - [ ] File discovery (glob patterns)
  - [ ] Outline parsing
  - [ ] Section extraction
- [ ] `api/documents.py` - Document endpoints
  - [ ] List documents
  - [ ] Get document content
  - [ ] Get line range
- [ ] Document reference endpoints
  - [ ] Create reference
  - [ ] List references for task
  - [ ] Delete reference

### Phase 4: Dashboard
- [ ] `templates/base.html` - Base layout with htmx/SSE
- [ ] `templates/dashboard.html` - Main task-centric dashboard
- [ ] `templates/partials/tasks.html` - Task list with actions
- [ ] `templates/partials/documents.html` - Document browser
- [ ] htmx interactions for all task actions
- [ ] SSE integration for real-time updates

### Phase 5: Polish
- [ ] Error handling
  - [ ] tmux session not found
  - [ ] Claude crash detection
  - [ ] GitButler failures
- [ ] Edge cases
  - [ ] Task tmux dies unexpectedly
  - [ ] Claude hangs (no output)
  - [ ] Branch conflicts
- [ ] Desktop notifications (`services/notifier.py`)
- [ ] Manual testing checklist

## Notes

### Architecture Decision: Hooks over Polling (2025-12-29)
Changed from terminal polling to Claude Code hooks for status detection:
- **Before**: Poll tmux output every 1s, regex pattern matching for status
- **After**: Claude Code hooks fire events, POST to Chorus API instantly

Benefits:
- Instant status updates (no 1s polling delay)
- Deterministic events (no fragile pattern matching)
- Lower resource usage
- Access to session metadata (transcript_path, session_id)

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
