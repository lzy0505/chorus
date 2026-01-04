# Implementation Plan

> Reference: See `design.md` for full specification

## Current Status (2026-01-04)

**Completed:** Phases 1-7, GitButler hooks integration, enhanced UX features ✅
**Current:** Phase 8.4 - Granular status tracking 🔄
**Next:** Document management, error termination detection, polish & reliability

---

## Current Phase: Enhanced UX Features (Phase 8) 🔄

### Phase 8.1: Permission Configuration ✅ (COMPLETED 2026-01-01)
- Implemented per-task permission policies using PermissionRequest hooks
- Per-task Claude config isolation (`CLAUDE_CONFIG_DIR`)
- Permission handler script with pattern-based filtering
- Predefined permission profiles (read_only, safe_edit, full_dev, git_only)

**Note:** PermissionRequest hooks approach later replaced by detection-based approach (2026-01-04) for better `-p` mode compatibility.

### Phase 8.2: Task Continuation UI ✅ (COMPLETED 2026-01-01)
- Added "Continue Task" button with `--resume` support
- Prompt history tracking and display
- Session ID preservation and display
- Continuation count tracking

### Phase 8.3: JSON Events Viewer ✅ (COMPLETED 2026-01-02)
- Interactive collapsible event cards with type-specific badges
- Tool pairing (combines tool_use + tool_result)
- Markdown rendering for assistant text
- State preservation during auto-refresh
- Eliminated visual flashing with CSS optimizations

### Phase 8.4: Granular Status Tracking 🔄
**Goal:** Show what Claude is actually doing from JSON events

- [ ] Expand ClaudeStatus enum (thinking, reading, editing, running)
- [ ] Implement `_update_status_from_event()` in json_monitor
- [ ] Extract activity context from events ("Editing main.py", "Running git status")
- [ ] Update UI to show status + activity
- [ ] Add status icons/colors

### Phase 8.5: Error vs Normal Termination
**Goal:** Distinguish between success and failure

- [ ] Detect normal termination (result with stopReason: "end_turn")
- [ ] Detect error termination (error events)
- [ ] Detect user cancellation (no result event)
- [ ] UI shows different actions based on termination type

---

## Next Phases

### Phase 4: Document Management
- [ ] `services/documents.py` - Document manager with file discovery
- [ ] `api/documents.py` - Document endpoints
- [ ] Document reference endpoints for task context
- [ ] UI for document viewing and referencing

### Phase 5: Polish & Reliability
- [ ] Desktop notifications (`services/notifier.py`)
- [ ] Comprehensive manual testing checklist
- [ ] Error recovery scenarios
- [ ] Integration tests with tmux

---

## Completed Phases (Summary)

### Phase 1: Core Foundation ✅ (2025-12-29)
Project structure, config, SQLModel definitions, database setup, tmux service wrapper

### Phase 2: Task API + JSON Monitoring ✅ (2025-12-29)
Task-centric tmux operations, JSON event parsing, monitoring service, GitButler CLI integration, task lifecycle endpoints, SSE

### Phase 3: Dashboard ✅ (2025-12-29)
Base layout with htmx/SSE, task-centric dashboard, HTML partials, dark theme styling

### Phase 6: GitButler Hooks Integration ✅ (2025-12-31)
**Architecture:** Task UUID = GitButler session (persistent across Claude restarts)

- UUID migration (Task.id is UUID primary key)
- Hook methods: `call_pre_tool_hook()`, `call_post_tool_hook()`, `call_stop_hook()`
- Transcript system (`/tmp/chorus/task-{uuid}/transcript.json`)
- Stack discovery after first edit
- Integrated into `json_monitor.py`
- Comprehensive unit tests (310 passing)

**Key Innovation:** Task UUID serves triple duty:
1. Task identifier in Chorus database
2. Claude session_id for `--resume`
3. GitButler session identifier for hooks

### Phase 7: JSON Monitoring Enhancements ✅ (2026-01-01)
**Documentation:** Deep understanding of Claude Code behavior

- `docs/JSON_EVENTS.md` - 10 event types fully documented
- `docs/TERMINATION_HANDLING.md` - `-p` flag behavior, multi-step tasks
- `docs/PERMISSION_HANDLING.md` - `--allowedTools`, permission profiles
- `docs/STATUS_TRACKING.md` - Granular status tracking design
- Termination detection implementation (detect tmux session exit)

---

## Key Documentation

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Development guide, GitButler workflow, project structure |
| `design.md` | Architecture, data models, API spec, implementation details |
| `TODO.md` | Current tasks and upcoming work |
| `README.md` | Quick start, features, configuration |
| `docs/JSON_EVENTS.md` | Claude Code JSON event format (10 event types) |
| `docs/TERMINATION_HANDLING.md` | Process termination, `-p` flag, session resumption |
| `docs/PERMISSION_HANDLING.md` | Permission configuration, `--allowedTools`, profiles |
| `docs/STATUS_TRACKING.md` | Granular status tracking, activity context, UI design |

---

## Notes

### GitButler Hooks - "Task as Logical Session"

**Key Concept:** A Chorus Task = single GitButler session, even with multiple Claude restarts.

```
Task (UUID: abc-123)
  = GitButler session_id: abc-123 (persistent)
  = Transcript: /tmp/chorus/task-abc-123/
  ├─ Claude session 1 (xyz-111) → edits use task_id
  ├─ [crashes/restarts]
  └─ Claude session 2 (xyz-222) → edits STILL use task_id

Result: All edits → same GitButler stack!
```

**Hook Workflow:**
1. tool_use event → `call_pre_tool_hook(task_uuid, file_path)`
2. [Claude edits file]
3. tool_result event → `call_post_tool_hook(task_uuid, file_path)`
4. GitButler auto-creates stack (first edit only): "zl-branch-15"
5. `discover_stack_for_session(task_uuid, file_path)` → save to task
6. `commit_to_stack(stack_name)`

### JSON Monitoring Migration (2025-12-31)

Completed migration from Claude Code hooks (SessionStart, ToolUse) to JSON event parsing:

**Benefits:**
- Instant, deterministic event detection
- Structured data instead of regex pattern matching
- Built-in session resumption support (`session_id` from JSON)
- Simpler architecture

**Important Terminology:**
- **Claude Code hooks** (DEPRECATED) = Callbacks like SessionStart, ToolUse - replaced by JSON mode
- **GitButler hooks** (IN USE) = `but claude pre-tool/post-tool/stop` - for stack isolation

### Logging System (2025-12-30)

- `services/logging_utils.py` - Logging utility functions
- Configurable levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Subprocess logging for tmux/GitButler CLI/ttyd
- API request logging
- Set `level = "DEBUG"` in `chorus.toml` for troubleshooting
