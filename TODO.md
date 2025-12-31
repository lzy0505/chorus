# TODO

> Auto-updated by Claude Code. Last update: 2025-12-31 01:36

### GitButler Hook Integration (Priority: High)
**Goal:** Complete GitButler hook integration for auto-stack creation per task

**UUID Migration - COMPLETED ✅ (2025-12-31)**
- ✅ Updated `models.py` - Task.id is now UUID (primary key)
- ✅ Updated `models.py` - Added `stack_name` and `stack_cli_id` fields
- ✅ Database supports UUID primary keys
- ✅ All API endpoints accept/return UUID task IDs
- ✅ Frontend templates handle UUID task IDs
- ✅ DocumentReference.task_id updated to UUID foreign key

**GitButler Hook Methods - COMPLETED ✅ (2025-12-31)**
- ✅ Implemented `discover_stack_for_session()` in `services/gitbutler.py:556`
- ✅ Implemented `call_pre_tool_hook()` in `services/gitbutler.py:435`
- ✅ Implemented `call_post_tool_hook()` in `services/gitbutler.py:475`
- ✅ Implemented `call_stop_hook()` in `services/gitbutler.py:522`
- ✅ Tests written in `tests/test_gitbutler.py`

**Hook Integration - REMAINING WORK ❌**
- [ ] Update `services/json_monitor.py:_handle_event()`:
  - [ ] Extract file_path from tool_use events
  - [ ] Call `gitbutler.call_pre_tool_hook()` on tool_use (Edit/Write/MultiEdit)
  - [ ] Call `gitbutler.call_post_tool_hook()` on tool_result success
  - [ ] Call `gitbutler.discover_stack_for_session()` after first successful edit
  - [ ] Save discovered stack_name and stack_cli_id to task
- [ ] Update `services/tmux.py` (task start):
  - [ ] Create transcript directory: `/tmp/chorus/task-{uuid}/`
  - [ ] Write transcript file: `{"type":"user","cwd":"{project_root}"}`
  - [ ] Pass transcript path to Claude session
- [ ] Update `api/tasks.py` (task completion):
  - [ ] Call `gitbutler.call_stop_hook()` with task UUID and transcript path
  - [ ] Cleanup transcript directory after task completes
- [ ] Integration testing:
  - [ ] Create two concurrent tasks
  - [ ] Edit files in both sessions
  - [ ] Verify GitButler auto-creates separate stacks (zl-branch-*)
  - [ ] Verify commits go to correct stacks

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

**Current vs Target State:**
- ✅ UUID migration complete
- ✅ Hook methods implemented
- ❌ Hooks not yet called by json_monitor
- ❌ Transcript files not yet created
