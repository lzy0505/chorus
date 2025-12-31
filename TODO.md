# TODO

> Auto-updated by Claude Code. Last update: 2025-12-31 01:28

### UUID + GitButler Hooks Migration (Priority: High)
**Goal:** Eliminate global state and enable perfect concurrent task isolation

**Research Completed:**
- ✅ Reverse-engineered GitButler Claude hooks JSON format
- ✅ Confirmed hooks create per-session stacks without marking
- ✅ Validated concurrent session isolation (different UUIDs → different auto-stacks)

**Implementation Tasks:**
- [ ] Update `models.py` - Change Task.id from Integer to UUID
- [ ] Update `models.py` - Replace `stack_id` with `stack_name` and `stack_cli_id`
- [ ] Create database migration script
- [ ] Update `services/gitbutler.py`:
  - [ ] Add `discover_stack_for_session(session_id, edited_file)` method
  - [ ] Add `call_pre_tool_hook(session_id, file_path, transcript_path)`
  - [ ] Add `call_post_tool_hook(session_id, file_path, transcript_path)`
  - [ ] Add `call_stop_hook(session_id, transcript_path)`
- [ ] Update `services/json_monitor.py`:
  - [ ] Call pre-tool hook on `tool_use` events (Edit/Write/MultiEdit)
  - [ ] Call post-tool hook on `tool_result` events (success)
  - [ ] Discover and save stack name/CLI ID after first edit
  - [ ] Call stop hook on task completion
- [ ] Update `services/tmux.py`:
  - [ ] Create transcript file on task start: `{"type":"user","cwd":"..."}`
  - [ ] Ensure transcript directory exists
- [ ] Update all API endpoints to use UUID:
  - [ ] `api/tasks.py` - All task routes
  - [ ] `api/dashboard.py` - Dashboard routes
  - [ ] `api/events.py` - SSE filtering
- [ ] Update frontend templates:
  - [ ] Task list rendering
  - [ ] Task detail views
  - [ ] HTMX swap targets
- [ ] Testing:
  - [ ] Create two tasks concurrently
  - [ ] Edit files in both sessions simultaneously
  - [ ] Verify each gets its own auto-stack
  - [ ] Verify commits go to correct stacks
  - [ ] Verify no global state conflicts
- [ ] Cleanup:
  - [ ] Remove old stack marking code
  - [ ] Remove reassignment logic
  - [ ] Update documentation

## Up Next

### Document Management (Phase 4)
- [ ] Implement document discovery and tracking
- [ ] Add document reference UI
- [ ] Context injection for tasks

### Polish & Reliability
- [ ] Desktop notifications for permission requests
- [ ] Comprehensive manual testing checklist
- [ ] Error recovery scenarios

## Completed

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

### Why UUID Migration is Critical

**Problem with Integer IDs:**
- GitButler hooks need a session identifier to create isolated stacks
- Using integer task IDs as session IDs doesn't work (not valid UUIDs)
- Maintaining separate mappings (task ID → session UUID) adds complexity
- No clean way to associate task → Claude session → GitButler session

**Solution with UUID:**
- One identifier for everything: Task ID = Claude session_id = GitButler session
- GitButler hooks automatically create stacks per UUID
- No global marking needed
- Perfect concurrent task isolation
- Simpler code, fewer moving parts

### Hook Call Timing

```
tool_use event → pre-tool hook → [file edited by Claude] → tool_result event → post-tool hook → discover stack → commit
```

First edit creates the stack, subsequent edits reuse it.
