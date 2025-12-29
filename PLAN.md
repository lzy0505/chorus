# Implementation Plan

> Reference: See `design.md` for full specification

## Current Phase: Phase 2 - Task API + Monitor (tmux focus) 🔄

### Phase 1: Core Foundation ✅
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions (Task, Document, DocumentReference)
- [x] Database setup
- [x] tmux service wrapper (basic commands)

### Phase 2: Task API + Monitor 🔄

**Priority: tmux and task lifecycle management**

- [x] Update `services/tmux.py` - Task-centric tmux operations ✅
  - [x] `create_task_session(task_id)` - Create tmux for a task
  - [x] `start_claude(task_id)` - Launch Claude in task's tmux
  - [x] `restart_claude(task_id)` - Kill and relaunch Claude
  - [x] `kill_task_session(task_id)` - Kill task's tmux
  - [x] `capture_output(task_id)` - Get terminal output
  - [x] `send_keys(task_id, text)` - Send input to Claude

- [ ] `services/detector.py` - Claude status detection
  - [ ] `detect_claude_status(output)` → (ClaudeStatus, permission_prompt)
  - [ ] Idle patterns: `>`, `claude>`
  - [ ] Waiting patterns: `(y/n)`, `Allow?`, etc.

- [ ] `services/gitbutler.py` - GitButler MCP integration
  - [ ] `create_branch(name)` - Create feature branch
  - [ ] `commit_changes(message)` - Commit via update_branches

- [ ] `api/tasks.py` - Task lifecycle endpoints
  - [ ] `POST /api/tasks` - Create task
  - [ ] `GET /api/tasks` - List tasks
  - [ ] `GET /api/tasks/{id}` - Get task details
  - [ ] `PUT /api/tasks/{id}` - Update task
  - [ ] `POST /api/tasks/{id}/start` - Start task (branch + tmux + Claude)
  - [ ] `POST /api/tasks/{id}/restart-claude` - Restart Claude session
  - [ ] `POST /api/tasks/{id}/send` - Send message to Claude
  - [ ] `POST /api/tasks/{id}/respond` - Respond to permission prompt
  - [ ] `POST /api/tasks/{id}/complete` - Complete task (commit + cleanup)
  - [ ] `POST /api/tasks/{id}/fail` - Mark task as failed
  - [ ] `DELETE /api/tasks/{id}` - Delete pending/failed task

- [ ] `services/monitor.py` - Task polling loop
  - [ ] Async polling every 1 second
  - [ ] Detect Claude status changes
  - [ ] Update task.claude_status
  - [ ] Emit SSE events

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

### Architecture Decision (2025-12-29)
Changed from session-centric to task-centric design:
- **Before**: Session (tmux) was primary, Task was assigned to Session
- **After**: Task is primary, each Task has its own tmux + GitButler branch

Key insight: Claude sessions are ephemeral (can hang, lose context) but the Task and its tmux persist. This allows restarting Claude without losing task progress.

### GitButler Integration
Using GitButler MCP commands:
- `gitbutler mcp create_branch --name {name}` - Create feature branch
- `gitbutler mcp update_branches` - Sync changes (commit)

### Removed
- `Session` model (replaced by task.tmux_session field)
- `api/sessions.py` (session management now part of task API)
- Separate session/task relationship
