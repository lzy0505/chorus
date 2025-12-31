# Implementation Plan

> Reference: See `design.md` for full specification

## Current Phase: UUID + GitButler Hooks Migration 🔄

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

### Phase 6: UUID + GitButler Hooks 🔄
**PARTIALLY COMPLETE: UUID migration done, hook integration pending**

**Completed:**
- [x] Update `models.py` - Change Task.id from Integer to UUID ✅
- [x] Update `models.py` - Replace `stack_id` with `stack_name` and `stack_cli_id` ✅
- [x] Database supports UUID primary keys ✅
- [x] Update `services/gitbutler.py` - Add hook methods ✅
  - [x] `discover_stack_for_session()` ✅
  - [x] `call_pre_tool_hook()` ✅
  - [x] `call_post_tool_hook()` ✅
  - [x] `call_stop_hook()` ✅
- [x] Update all API endpoints to use UUID task IDs ✅
- [x] Update frontend to handle UUID task IDs ✅

**Remaining:**
- [ ] Update `services/json_monitor.py` - Integrate GitButler hooks
  - [ ] Call pre-tool hook before file edits
  - [ ] Call post-tool hook after file edits
  - [ ] Stack discovery after first edit
  - [ ] Save discovered stack to task
- [ ] Update `services/tmux.py` - Create transcript files for hooks
- [ ] Update `api/tasks.py` - Call stop hook on task completion
- [ ] Test concurrent tasks with hooks
- [ ] Clean up old stack marking code (if any remains)

## Notes

### UUID + GitButler Hooks Architecture (2025-12-31)

**Major architecture change to eliminate global state and enable perfect task isolation:**

**Problem Solved:**
- Previous approach required `but mark` to assign changes to stacks (global state)
- Concurrent tasks would conflict - only one stack could be marked at a time
- Needed complex reassignment logic to move files between stacks

**New Solution:**
- Task ID = UUID (not auto-increment integer)
- UUID serves triple duty: Task ID, Claude session_id, GitButler session identifier
- GitButler hooks (`but claude pre-tool`, `post-tool`, `stop`) automatically create and manage stacks per session
- Each task UUID → unique auto-created stack (e.g., "zl-branch-15")
- No marking, no reassignment, no global state

**Workflow:**
1. Create task → Generate UUID
2. Start Claude → Use UUID as session_id
3. File edited → Call pre-tool hook with UUID
4. File saved → Call post-tool hook with UUID
5. GitButler auto-creates stack for that UUID (first edit only)
6. Discover stack name from GitButler status
7. Commit to that stack
8. Task complete → Call stop hook

**Benefits:**
- ✅ Perfect isolation between concurrent tasks
- ✅ No global state (no marking)
- ✅ No reassignment logic needed
- ✅ Clean 1:1 mapping: UUID = Session = Stack
- ✅ Simpler code, more reliable

### JSON Monitoring Migration (2025-12-31)

Completed migration from **Claude Code hooks** (SessionStart, ToolUse, etc.) to JSON event parsing:

**What Changed:**
- Claude sessions now launch with `--output-format stream-json`
- Status detection via structured JSON events (deterministic, no regex)
- Session resumption via `session_id` extracted from JSON events
- **Note:** Legacy files `services/hooks.py` and `services/status_detector.py` still exist but are only used in legacy mode (`use_json_mode = false`)

**Benefits:**
- Instant, deterministic event detection
- Structured data instead of regex pattern matching
- Built-in session resumption support
- Simpler architecture

**Important Terminology Distinction:**
- **Claude Code hooks** = OLD monitoring method (SessionStart, ToolUse callbacks) - replaced by JSON mode
- **GitButler hooks** = `but claude pre-tool/post-tool/stop` - for stack isolation, NOT yet integrated

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

### Architecture Decision: Task-Centric Design (2025-12-29)
Changed from session-centric to task-centric design:
- **Before**: Session (tmux) was primary, Task was assigned to Session
- **After**: Task is primary, each Task has its own tmux + GitButler stack

Key insight: Claude sessions are ephemeral (can hang, lose context) but the Task and its tmux persist. This allows restarting Claude without losing task progress.

### GitButler Integration (Updated 2025-12-31)

**Using GitButler Claude Hooks:**

```bash
# Called by Chorus automatically during file edits
echo '{"session_id":"task-uuid","transcript_path":"/tmp/...","hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"..."}}' | but claude pre-tool -j

echo '{"session_id":"task-uuid","transcript_path":"/tmp/...","hook_event_name":"PostToolUse","tool_name":"Edit","tool_input":{"file_path":"..."},"tool_response":{"filePath":"...","structuredPatch":[]}}' | but claude post-tool -j

echo '{"session_id":"task-uuid","transcript_path":"/tmp/...","hook_event_name":"SessionEnd"}' | but claude stop -j

# Traditional commands still used for commits and queries
but commit {stack-name}              # Commit to auto-created stack
but status -j                        # Get workspace status (discover stacks)
but branch delete {stack} --force    # Cleanup if needed
```

**Per-Task Stack Assignment (Hook-managed):**
GitButler automatically creates and assigns stacks based on session UUID:

1. File edit occurs → Chorus calls `but claude pre-tool` with task UUID
2. File saved → Chorus calls `but claude post-tool` with task UUID
3. GitButler creates stack for this UUID (e.g., "zl-branch-15") on first edit
4. Chorus discovers stack name via `but status -j`
5. Chorus commits: `but commit {discovered-stack-name}`

```
tmux-1 (UUID-aaa): Claude edits → pre/post hooks → GitButler creates zl-branch-10
tmux-2 (UUID-bbb): Claude edits → pre/post hooks → GitButler creates zl-branch-11
```

**No marking, no reassignment, perfect isolation.**

### Removed
- `Session` model (replaced by task.tmux_session field)
- `api/sessions.py` (session management now part of task API)
- Separate session/task relationship
