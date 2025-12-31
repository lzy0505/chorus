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

### Phase 6: GitButler Hooks - "Task as Logical Session" 🔄
**IN PROGRESS: Architecture finalized, implementation pending**

#### Architecture: Task as Logical Session

**Key Concept:** A Chorus **Task** = single GitButler **session**, even with multiple Claude restarts.

```
Task (UUID: abc-123)
  = GitButler session_id: abc-123 (persistent)
  = Transcript: /tmp/chorus/task-abc-123/
  ├─ Claude session 1 (xyz-111) → edits use task_id
  ├─ [crashes/restarts]
  └─ Claude session 2 (xyz-222) → edits STILL use task_id

Result: All edits → same GitButler stack!
```

**Two UUIDs:**
- **Task UUID** (`task.id`): GitButler session_id, persistent
- **Claude UUID**: For `--resume`, changes on restart

#### Completed ✅
- [x] UUID migration: Task.id is UUID primary key
- [x] Database fields: `stack_name`, `stack_cli_id`
- [x] Hook methods: `call_pre_tool_hook()`, `call_post_tool_hook()`, `call_stop_hook()`
- [x] Stack discovery: `discover_stack_for_session()`
- [x] Documentation: Architecture finalized

#### Implementation Tasks ✅ (COMPLETED 2025-12-31)

**1. `services/tmux.py`**
- [x] Add helper functions: `get_transcript_dir()`, `create_transcript_file()`
- [x] Update `create_task_session()`: Create transcript on task start
- [x] Add cleanup in `kill_task_session()`

**2. `models.py`**
- [x] Add field: `claude_session_id: Optional[str]` (for --resume)

**3. `services/json_monitor.py`**
- [x] Add GitButlerService integration
- [x] On `tool_use` (Edit/Write/MultiEdit): Call `pre_tool_hook(task.id, ...)`
- [x] On `tool_result` success: Call `post_tool_hook(task.id, ...)`
- [x] On first successful edit: Discover and save stack
- [x] Extract Claude session_id for --resume

**4. `api/tasks.py`**
- [x] On task completion: Call `stop_hook(task.id, ...)`
- [x] Cleanup transcript directory (handled by tmux)
- [x] Update all task_id parameters from int to UUID

#### Testing ✅ (COMPLETED 2025-12-31)
- [x] Unit: Transcript creation
- [x] Unit: Hook integration (5 tests covering all hook workflows)
- [x] Unit: Stop hook on task completion
- [ ] Integration: Single task with Claude restart (manual testing required)
- [ ] Integration: Concurrent tasks → separate stacks (manual testing required)

**Test Suite Status:**
- 310 passing tests
- All hook integration tests passing
- 32 failing tests in legacy code (hooks API, UUID migrations)

## Notes

### GitButler Hooks - Detailed Implementation (2025-12-31)

#### Architecture: Task as Logical Session

**Key Innovation:** Task UUID = GitButler session (persistent across Claude restarts)

**Two UUIDs:**
1. **Task UUID** (`task.id`) - GitButler session_id, persistent
2. **Claude UUID** - For `--resume`, changes on restart

**Data Flow:**

1. **Task Created** → Create transcript `/tmp/chorus/task-{uuid}/transcript.json`
2. **Claude Started** → Generate new Claude UUID, use for `--resume`
3. **File Edited** → Call `pre_tool_hook(session_id=task.id, ...)`
4. **File Saved** → Call `post_tool_hook(session_id=task.id, ...)`
5. **First Edit** → Discover stack, save `stack_name` to task
6. **Claude Restart** → New Claude UUID, same task.id for hooks!
7. **More Edits** → Still use task.id, same stack ✅
8. **Task Complete** → Call `stop_hook(session_id=task.id)`

#### Code Changes

**`services/tmux.py`:**
```python
def get_transcript_dir(task_id: UUID) -> Path:
    return Path(f"/tmp/chorus/task-{task_id}")

def create_transcript_file(task_id: UUID, project_root: str) -> Path:
    # Create JSONL file with minimal entry
    # session_id = task_id
```

**`models.py`:**
```python
claude_session_id: Optional[str] = None  # For --resume
```

**`services/json_monitor.py`:**
```python
# On tool_use: call_pre_tool_hook(task.id, file_path, ...)
# On tool_result: call_post_tool_hook(task.id, file_path, ...)
# First edit: discover_stack_for_session() → save to task
```

**`api/tasks.py`:**
```python
# On completion: call_stop_hook(task.id, ...)
# Cleanup transcript directory
```

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
