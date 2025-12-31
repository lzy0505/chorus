# GitButler Hook Integration - Implementation Plan

## Architecture Overview

### Core Concept: Task as Logical Session

**Key Insight:** A Chorus **Task** maps to a single GitButler **session**, even if multiple Claude Code sessions are spawned for that task.

```
Task (UUID: abc-123)
  = GitButler session_id: abc-123
  = Transcript: /tmp/chorus/task-abc-123/transcript.json
  = Tmux session: chorus-task-abc-123
  ├─ Claude session 1 (initial, session_id: xyz-111)
  │   └─ Edits files → hooks use task_id (abc-123)
  ├─ [Claude crashes/restarts]
  └─ Claude session 2 (resumed, session_id: xyz-222)
      └─ Edits files → hooks STILL use task_id (abc-123)

Result: All edits assigned to the same GitButler stack!
```

### Two Different UUIDs

1. **Task UUID** (`task.id`)
   - Created when task is created
   - Used as `session_id` in GitButler hooks
   - Persistent across all Claude restarts
   - Maps to a single GitButler stack

2. **Claude Session UUID** (stored in task metadata)
   - Generated each time Claude starts
   - Used for Claude Code's `--resume` flag
   - Changes on each restart
   - Only for Claude's internal use

## Implementation Changes

### 1. `services/tmux.py`

#### New Functions

```python
def get_transcript_dir(task_id: UUID) -> Path:
    """Get transcript directory: /tmp/chorus/task-{uuid}/"""
    return Path(f"/tmp/chorus/task-{task_id}")

def create_transcript_file(task_id: UUID, project_root: str) -> Path:
    """Create minimal JSONL transcript for GitButler hooks."""
    # Create /tmp/chorus/task-{uuid}/transcript.json
    # Format: one JSON object per line (JSONL)
    # Minimal entry with session_id = task_id
```

#### Modified Methods

**`create_task_session(task_id: UUID) -> str`**
- Add: Create transcript directory and file
- Call: `create_transcript_file(task_id, self.project_root)`

**`kill_task_session(task_id: UUID)`** (if exists, or create new method)
- Add: Cleanup transcript directory
- Remove: `/tmp/chorus/task-{task_id}/`

### 2. `services/json_monitor.py`

#### New Dependencies

```python
from services.gitbutler import GitButlerService
from services.tmux import get_transcript_dir
```

#### Modified `JSONMonitor` Class

**Add fields:**
```python
self.gitbutler = GitButlerService(project_root)
self.transcript_dir = get_transcript_dir(task.id)
self.transcript_path = str(self.transcript_dir / "transcript.json")
self.stack_discovered = False  # Track if we've discovered the stack yet
```

**Modify `_handle_event()` method:**

```python
def _handle_event(self, event: dict):
    event_type = event.get("type")

    # Extract Claude session_id for resumption (independent of hooks)
    if event_type == "result" and not self.task.claude_session_id:
        self.task.claude_session_id = event.get("sessionId")
        # Save to DB

    # Handle tool_use events (Edit/Write/MultiEdit)
    if event_type == "tool_use":
        tool_name = event.get("toolName")
        if tool_name in ["Edit", "Write", "MultiEdit"]:
            tool_input = event.get("toolInput", {})
            file_path = tool_input.get("file_path")

            if file_path:
                # Call pre-tool hook with TASK UUID (not Claude session_id)
                self.gitbutler.call_pre_tool_hook(
                    session_id=str(self.task.id),
                    file_path=file_path,
                    transcript_path=self.transcript_path,
                    tool_name=tool_name
                )

    # Handle tool_result events (success)
    elif event_type == "tool_result":
        tool_use_id = event.get("toolUseId")
        # Find corresponding tool_use event to get file_path
        tool_use_event = self._find_tool_use_by_id(tool_use_id)

        if tool_use_event:
            tool_name = tool_use_event.get("toolName")
            if tool_name in ["Edit", "Write", "MultiEdit"]:
                tool_input = tool_use_event.get("toolInput", {})
                file_path = tool_input.get("file_path")

                if file_path:
                    # Call post-tool hook
                    self.gitbutler.call_post_tool_hook(
                        session_id=str(self.task.id),
                        file_path=file_path,
                        transcript_path=self.transcript_path,
                        tool_name=tool_name
                    )

                    # Discover stack after first successful edit
                    if not self.stack_discovered:
                        stack_info = self.gitbutler.discover_stack_for_session(
                            session_id=str(self.task.id),
                            edited_file=file_path
                        )
                        if stack_info:
                            stack_name, stack_cli_id = stack_info
                            self.task.stack_name = stack_name
                            self.task.stack_cli_id = stack_cli_id
                            self.stack_discovered = True
                            # Save to DB
                            logger.info(f"Discovered stack for task {self.task.id}: {stack_name}")
```

**Add helper method:**
```python
def _find_tool_use_by_id(self, tool_use_id: str) -> Optional[dict]:
    """Find tool_use event by its ID from recent events."""
    # Look through recent events for matching tool_use
    # (Implementation depends on how events are buffered)
```

### 3. `api/tasks.py`

#### Modified Endpoints

**`POST /tasks/{task_id}/complete`** (or wherever task completion happens)

```python
from services.gitbutler import GitButlerService
from services.tmux import get_transcript_dir

# On task completion:
gitbutler = GitButlerService()
transcript_dir = get_transcript_dir(task.id)
transcript_path = str(transcript_dir / "transcript.json")

# Call stop hook
gitbutler.call_stop_hook(
    session_id=str(task.id),
    transcript_path=transcript_path
)

# Cleanup transcript directory
import shutil
shutil.rmtree(transcript_dir, ignore_errors=True)
logger.debug(f"Cleaned up transcript directory: {transcript_dir}")
```

### 4. `models.py`

#### Check/Add Fields

Ensure `Task` model has:
```python
id: UUID  # Primary key - used as GitButler session_id ✅
claude_session_id: Optional[str] = None  # For --resume, changes on restart
stack_name: Optional[str] = None  # Discovered after first edit ✅
stack_cli_id: Optional[str] = None  # GitButler CLI ID ✅
```

### 5. `services/gitbutler.py`

**No changes needed!** ✅
- `call_pre_tool_hook()` - already implemented
- `call_post_tool_hook()` - already implemented
- `call_stop_hook()` - already implemented
- `discover_stack_for_session()` - already implemented

## Data Flow

### Task Creation → First Edit

1. **Task Created** (`POST /tasks`)
   - Generate UUID for task
   - Create tmux session
   - **NEW:** Create transcript file `/tmp/chorus/task-{uuid}/transcript.json`

2. **Claude Started** (`start_claude_json_mode`)
   - Generate new Claude session UUID
   - Start Claude with `--resume {claude_session_uuid}` (if restarting)
   - Claude UUID stored separately from task UUID

3. **File Edited** (JSON monitor detects `tool_use` event)
   - Extract file_path from event
   - **NEW:** Call `pre-tool` hook with `session_id=task.id`
   - GitButler receives hook with task UUID

4. **File Saved** (JSON monitor detects `tool_result` event)
   - **NEW:** Call `post-tool` hook with `session_id=task.id`
   - GitButler creates/updates stack for this session
   - **NEW:** Discover stack name (first edit only)
   - Save `stack_name` and `stack_cli_id` to task

5. **More Edits**
   - Continue calling pre/post hooks with same `session_id=task.id`
   - All edits go to same stack automatically

### Claude Restart

6. **Claude Crashes/Restarts**
   - Kill Claude process
   - Generate NEW Claude session UUID
   - Start Claude with `--resume {new_claude_uuid}`
   - **Keep using same task.id for hooks!**

7. **More Edits After Restart**
   - Hooks still use `session_id=task.id`
   - GitButler sees same session, assigns to same stack ✅

### Task Completion

8. **Task Completes** (`POST /tasks/{id}/complete`)
   - **NEW:** Call `stop` hook with `session_id=task.id`
   - **NEW:** Cleanup transcript directory
   - Kill tmux session

## Testing Plan

### Unit Tests

1. **`test_tmux.py`**
   - `test_create_transcript_file()` - verify JSONL format
   - `test_get_transcript_dir()` - verify path format
   - `test_create_task_session_creates_transcript()`

2. **`test_json_monitor.py`**
   - `test_pre_tool_hook_called_on_edit()`
   - `test_post_tool_hook_called_on_save()`
   - `test_stack_discovery_after_first_edit()`
   - `test_hooks_use_task_uuid_not_claude_uuid()`

3. **`test_tasks_api.py`**
   - `test_stop_hook_called_on_completion()`
   - `test_transcript_cleanup_on_completion()`

### Integration Tests

1. **Single Task Workflow**
   - Create task
   - Start Claude
   - Edit file
   - Verify stack created with task UUID
   - Complete task
   - Verify stop hook called

2. **Claude Restart Workflow**
   - Create task
   - Start Claude, edit file A
   - Restart Claude
   - Edit file B
   - Verify both files in same stack

3. **Concurrent Tasks**
   - Create task A and task B
   - Edit files in both
   - Verify separate stacks created
   - Verify no cross-contamination

## Migration Notes

### Breaking Changes

None! This is purely additive:
- Existing tasks without `stack_name` will get it on next edit
- New `claude_session_id` field is optional
- Transcript creation is automatic

### Compatibility

- GitButler hooks work with existing GitButler installations
- No changes to database schema (UUID already supported)
- Backward compatible with tasks created before this change

## Rollout Plan

1. ✅ Document architecture (this file)
2. ✅ Update DESIGN.md
3. ✅ Update TODO.md
4. ✅ Update CLAUDE.md (if needed)
5. Implement changes in order:
   - `services/tmux.py` (transcript creation)
   - `services/json_monitor.py` (hook integration)
   - `api/tasks.py` (stop hook)
6. Write unit tests
7. Write integration tests
8. Manual testing with real tasks
9. Deploy

## Success Criteria

✅ Multiple Claude restarts for same task → all edits in same stack
✅ Concurrent tasks → separate stacks, no conflicts
✅ Task completion → stop hook called, cleanup successful
✅ No regressions in existing functionality
