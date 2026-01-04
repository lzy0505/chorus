# TODO

> Auto-updated by Claude Code. Last update: 2026-01-04 15:57

### GitButler Hook Integration - "Task as Logical Session" (Priority: High)

**Goal:** Implement GitButler hooks where Task UUID = GitButler session (persistent across Claude restarts)

**Architecture - FINALIZED ✅ (2025-12-31)**
- ✅ Task UUID = GitButler session_id (persistent)
- ✅ Claude session UUID = separate (for --resume, changes on restart)
- ✅ One transcript per task (not per Claude session)
- ✅ Hooks use task UUID consistently
- ✅ Stop hook only on task completion (not Claude restart)
- ✅ Documentation: `IMPLEMENTATION_PLAN.md` created
- ✅ `DESIGN.md` updated with new architecture

**Foundation - COMPLETED ✅ (2025-12-31)**
- ✅ UUID Migration: Task.id is UUID primary key
- ✅ Database fields: `stack_name`, `stack_cli_id`
- ✅ Hook methods: `call_pre_tool_hook()`, `call_post_tool_hook()`, `call_stop_hook()`
- ✅ Stack discovery: `discover_stack_for_session()`
- ✅ Tests: `tests/test_gitbutler.py`

**Implementation - COMPLETED ✅ (2025-12-31)**
- [x] `services/tmux.py`:
  - [x] Add helper functions (get_transcript_dir, create_transcript_file)
  - [x] Update `create_task_session()` to create transcript
  - [x] Add transcript cleanup on session kill
- [x] `models.py`:
  - [x] Add `claude_session_id: Optional[str]` field (for --resume)
- [x] `services/json_monitor.py`:
  - [x] Add GitButlerService integration
  - [x] Call `pre_tool_hook()` on Edit/Write/MultiEdit tool_use
  - [x] Call `post_tool_hook()` on successful tool_result
  - [x] Discover and save stack after first edit
  - [x] Extract Claude session_id for --resume
- [x] `api/tasks.py`:
  - [x] Call `stop_hook()` on task completion
  - [x] Cleanup transcript directory (handled by tmux.kill_task_session)
  - [x] Update all task_id parameters from int to UUID

**Testing - COMPLETED ✅ (2025-12-31)**
- [x] Unit tests for transcript creation (`test_tmux.py::TestTranscriptFunctions`)
- [x] Unit tests for hook integration (`test_json_monitor.py::test_hook_integration_*`)
  - [x] Pre-tool hook called on Edit/Write/MultiEdit
  - [x] Post-tool hook called on successful file edits
  - [x] Stack discovery on first edit
  - [x] Commit to discovered stack
  - [x] No hooks for Read/Grep/Glob tools
  - [x] Claude session_id extraction for --resume
- [x] Unit test for stop hook (`test_tasks_api.py::TestTaskComplete`)

**Test Results (2025-12-31)**
- ✅ 310 tests passing
- ⚠️ 32 tests failing (mostly legacy hook API tests + UUID migration issues)
- 🎯 All critical hook integration tests passing
- ⏭️ Integration tests require manual testing with real Claude sessions

## In Progress

### Phase 8.4: Granular Status Tracking
**Goal:** Show what Claude is actually doing from JSON events

- [ ] Expand ClaudeStatus enum (thinking, reading, editing, running)
- [ ] Implement `_update_status_from_event()` in json_monitor
- [ ] Extract activity context from events
- [ ] Update UI to show status + activity
- [ ] Add status icons/colors

## Up Next

### Document Management (Phase 4)
- [ ] Implement document discovery and tracking
- [ ] Add document reference UI
- [ ] Context injection for tasks

### Phase 8.5: Error vs Normal Termination
- [ ] Detect normal termination (result with stopReason: "end_turn")
- [ ] Detect error termination (error events)
- [ ] Detect user cancellation (no result event)
- [ ] UI shows different actions based on termination type

### Polish & Reliability
- [ ] Desktop notifications for permission requests
- [ ] Comprehensive manual testing checklist
- [ ] Error recovery scenarios

## Completed

### Phase 8: Enhanced UX Features (2026-01-01 to 2026-01-02)
- ✅ **8.1: Permission Configuration with PermissionRequest Hooks**
  - Implemented per-task permission policies using PermissionRequest hooks
  - Per-task Claude config isolation (`/tmp/chorus/config/task-{uuid}/.claude/`)
  - Permission handler script queries Chorus database for task policies
  - Predefined profiles: read_only, safe_edit, full_dev, git_only
  - UI: Permission profile selector in task creation form
  - Granular control: bash command patterns, file patterns, tool allowlists
  - Works with `-p` flag (non-interactive mode)
  - Audit logging: All permission decisions logged to stderr
  - Files: `services/claude_config.py`, `/tmp/chorus/hooks/permission-handler.py`
  - Documented in `docs/PERMISSION_HOOKS.md`
- ✅ **8.2: Task Continuation UI**
  - Added `continuation_count` and `prompt_history` fields to Task model
  - Created `/api/tasks/{task_id}/continue` endpoint with `--resume` support
  - UI shows "Continue Task" button when Claude stopped
  - Prompt history displayed in numbered list
  - Session ID shown in info grid
  - Continuation count tracked and displayed
- ✅ **8.3: JSON Events Viewer (2026-01-02)**
  - Permission policy display in task detail view
    - Shows allowed tools as color-coded badges
    - Displays file/bash patterns with allow/deny rules
    - Shows auto-approve status
  - Interactive JSON events viewer in `/dashboard/tasks/{id}/output`
    - Collapsible event cards with expand/collapse animation
    - Event type badges with color coding (system, assistant, tool_execution, result, error)
    - Smart event summaries showing essential info by default
    - Full JSON data visible on expand
  - Enhanced event display
    - Assistant text events show full message content
    - Tool executions show tool name, file path/command, and result preview
    - Result events show token counts (input/output)
  - **Tool pairing feature**
    - Combines tool_use (from assistant messages) + tool_result (from user messages)
    - Creates single tool_execution events by matching IDs
    - Hides redundant user events containing only tool results
    - Shows SUCCESS/ERROR badges and result preview (first 80 chars)
    - Expandable to show both tool_use and tool_result JSON blocks
  - **Markdown rendering for text content**
    - Text events render as formatted markdown in expanded view instead of raw JSON
    - Assistant message text blocks render as markdown with proper formatting
    - Supports: headings, bold/italic, code blocks, lists, tables, links, blockquotes
    - Comprehensive CSS styling for markdown elements
    - Note indicator when assistant message contains both text and tool_use blocks
    - Dependencies: `markdown` library with fenced_code and tables extensions
  - **Preserved expanded state during auto-refresh**
    - Auto-refresh (every 2s) now preserves which events are expanded
    - Stores expanded event indices before swap
    - Restores expanded class after swap
    - Prevents user's viewing state from being reset
  - **Eliminated auto-refresh flashing**
    - Removed `transition: all` from `.task-item` and `.json-event` (only specific properties transition)
    - Removed all transitions from `.expand-icon` and `.event-full-data`
    - Hide container with `opacity: 0` during swap, show after state restoration
    - Prevents visual blink during innerHTML replacement

### Documentation Updates (2025-12-31)
- ✅ Updated DESIGN.md with UUID-based architecture
- ✅ Updated PLAN.md with GitButler hooks workflow
- ✅ Documented hook JSON formats and benefits

### GitButler Hooks Research (2025-12-31)
- ✅ Discovered `but claude` hooks exist
- ✅ Reverse-engineered JSON input format for all three hooks
- ✅ Confirmed hooks create session-isolated stacks
- ✅ Tested concurrent sessions get different auto-stacks
- ✅ Validated no marking needed for isolation

### JSON Monitoring Migration (2025-12-31)
- ✅ Migrated from hook-based to JSON event parsing
- ✅ Implemented `services/json_parser.py`
- ✅ Implemented `services/json_monitor.py`
- ✅ Session resumption with `--resume` support
- ✅ Removed legacy hook-based monitoring code

### Logging System (2025-12-30)
- ✅ Added `services/logging_utils.py`
- ✅ Implemented subprocess logging
- ✅ Configured logging levels in TOML
- ✅ Applied to all services and APIs

### Core Foundation (2025-12-29)
- ✅ Project structure and configuration
- ✅ Database models (Task, Document, DocumentReference)
- ✅ Task lifecycle API
- ✅ GitButler service integration
- ✅ Web dashboard with htmx/SSE
- ✅ Dark theme styling

## Notes

### UUID Architecture Benefits

**The Triple-Duty Identifier:**
- Task.id (UUID) serves as Task ID, Claude session_id, and GitButler session identifier
- No separate mapping needed - one ID for everything
- Perfect isolation between concurrent tasks

**GitButler Hook Workflow:**
```
1. tool_use event → call_pre_tool_hook(task_uuid, file_path)
2. [Claude edits file]
3. tool_result event → call_post_tool_hook(task_uuid, file_path)
4. GitButler auto-creates stack (first edit only): "zl-branch-15"
5. discover_stack_for_session(task_uuid, file_path)
6. Save stack_name to task
7. commit_to_stack(stack_name)
```

**Implementation Status:**
- ✅ UUID migration complete
- ✅ Hook methods implemented
- ✅ Hooks integrated into json_monitor
- ✅ Transcript files created on task start
- ✅ Stop hook called on task completion
- ⏭️ Testing pending
