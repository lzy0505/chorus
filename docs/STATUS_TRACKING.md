# Claude Status Tracking from JSON Events

## Current Implementation

### Status Enum (models.py)

```python
class ClaudeStatus(str, Enum):
    stopped = "stopped"      # Claude not running in tmux
    starting = "starting"    # Claude is initializing
    idle = "idle"            # Claude at prompt, waiting for input
    busy = "busy"            # Claude is processing
    waiting = "waiting"      # Claude asking for permission
```

### Current Event → Status Mapping

| Event Type | Status Transition | Notes |
|------------|------------------|-------|
| `session_start` | → `idle` | Session initialized, ready for input |
| `user` | → `busy` | Processing user input |
| `tool_use` | → `busy` | Executing a tool |
| `tool_result` | → `idle` | Tool completed, back to prompt |
| `text` | → `busy` | Generating response text |
| `assistant` | → `busy` | Sending complete message |
| `result` | → `idle` | Request completed |
| `permission_request` | → `waiting` | Waiting for user approval |
| `error` | (no change) | Error occurred |

**Issues with Current Approach:**
1. ❌ `busy` is too generic - doesn't distinguish between thinking, reading, editing, running commands
2. ❌ No visibility into *what* Claude is doing when busy
3. ❌ Status transitions can be confusing (e.g., `text` → `busy` even if Claude already was busy)
4. ❌ No distinction between "thinking about what to do" vs "actively executing a tool"

---

## Proposed Improvements

### Option 1: Granular Status with Activity Context

**Enhanced Status Enum:**
```python
class ClaudeStatus(str, Enum):
    stopped = "stopped"           # Not running
    starting = "starting"         # Initializing
    idle = "idle"                 # At prompt, waiting
    thinking = "thinking"         # Processing, planning response
    reading = "reading"           # Using Read/Grep/Glob tools
    editing = "editing"           # Using Edit/Write/MultiEdit tools
    running_command = "running"   # Using Bash tool
    waiting = "waiting"           # Waiting for permission
```

**Additional Context Field:**
```python
class Task:
    ...
    claude_status: ClaudeStatus
    claude_activity: Optional[str] = None  # e.g., "Editing main.py", "Running git status"
```

**Event Mapping:**
```python
match event_type:
    case "tool_use":
        tool_name = event.data.get("toolName")
        tool_input = event.data.get("toolInput", {})

        if tool_name in ["Read", "Grep", "Glob"]:
            status = ClaudeStatus.reading
            activity = f"Reading {tool_input.get('file_path', 'files')}"
        elif tool_name in ["Edit", "Write", "MultiEdit"]:
            status = ClaudeStatus.editing
            activity = f"Editing {tool_input.get('file_path', 'file')}"
        elif tool_name == "Bash":
            status = ClaudeStatus.running_command
            activity = f"Running: {tool_input.get('command', 'command')[:50]}"
        else:
            status = ClaudeStatus.busy
            activity = f"Using {tool_name}"

    case "text" | "assistant":
        status = ClaudeStatus.thinking
        activity = "Generating response"

    case "tool_result":
        status = ClaudeStatus.idle
        activity = None
```

**UI Presentation:**
```
Claude: editing • Editing services/json_monitor.py
Claude: running • Running: git status
Claude: thinking • Generating response
Claude: idle
```

---

### Option 2: Activity Timeline

Track a timeline of activities instead of single status:

```python
class Activity(SQLModel):
    task_id: UUID
    timestamp: datetime
    event_type: str      # "tool_use", "text", "result"
    description: str     # Human-readable description
    completed: bool
```

**UI Presentation:**
```
Current Activity:
├─ 14:23:45 Editing main.py ⏳
└─ 14:23:30 Read config.py ✓

Recent History:
├─ 14:23:15 Running git diff ✓
├─ 14:23:00 Thinking... ✓
└─ 14:22:45 User input ✓
```

---

### Option 3: State Machine Approach

Define clear state transitions:

```
       start
         ↓
      [idle] ←──────────────┐
         ↓                  │
    [user input]            │
         ↓                  │
    [thinking] ─→ [tool_use] ─→ [tool_result]
         ↓                         │
    [responding] ──────────────────┤
         ↓                         │
      [result] ─────────────────────┘

     [waiting] ←─ permission_request
         ↓
    [user confirms]
         ↓
      [idle]
```

**Benefits:**
- Clear, predictable state transitions
- Easier to debug
- Can validate state changes

---

## Recommended Approach

**Hybrid: Option 1 + Simplified Timeline**

1. **Granular Status**: Use enhanced status enum with activity context
2. **Current Activity Display**: Show `status + activity` prominently
3. **Recent Events**: Show last 3-5 events in compact format

### UI Layout

```
┌─────────────────────────────────────────┐
│ Task: Update README                      │
│                                          │
│ Claude: editing                          │
│ └─ Editing README.md                     │
│                                          │
│ Recent Activity:                         │
│ • 14:25:10 Edited README.md             │
│ • 14:24:55 Read CLAUDE.md               │
│ • 14:24:40 Generated response           │
└─────────────────────────────────────────┘
```

### Implementation Changes

**models.py:**
```python
class ClaudeStatus(str, Enum):
    stopped = "stopped"
    starting = "starting"
    idle = "idle"
    thinking = "thinking"
    reading = "reading"
    editing = "editing"
    running = "running"
    waiting = "waiting"

class Task(SQLModel, table=True):
    ...
    claude_status: ClaudeStatus
    claude_activity: Optional[str] = None  # Current activity description
```

**json_monitor.py:**
```python
def _update_status_from_event(self, task: Task, event: ClaudeJsonEvent):
    """Update task status based on event type and content."""
    event_type = event.event_type

    match event_type:
        case "session_start":
            task.claude_status = ClaudeStatus.idle
            task.claude_activity = None

        case "user":
            task.claude_status = ClaudeStatus.thinking
            task.claude_activity = "Processing request"

        case "tool_use":
            tool_name = event.data.get("toolName")
            tool_input = event.data.get("toolInput", {})
            task.claude_status, task.claude_activity = \
                self._get_tool_status(tool_name, tool_input)

        case "tool_result":
            task.claude_status = ClaudeStatus.thinking
            task.claude_activity = "Analyzing results"

        case "text" | "assistant":
            task.claude_status = ClaudeStatus.thinking
            task.claude_activity = "Writing response"

        case "result":
            task.claude_status = ClaudeStatus.idle
            task.claude_activity = None

        case "permission_request":
            task.claude_status = ClaudeStatus.waiting
            prompt = event.data.get("prompt", "")
            task.claude_activity = f"Needs approval: {prompt[:50]}"

def _get_tool_status(self, tool_name: str, tool_input: dict) -> tuple[ClaudeStatus, str]:
    """Determine status and activity from tool usage."""
    if tool_name in ["Read", "Grep", "Glob", "LSP"]:
        file_path = tool_input.get("file_path") or tool_input.get("path", "files")
        return ClaudeStatus.reading, f"Reading {Path(file_path).name if file_path else 'files'}"

    elif tool_name in ["Edit", "Write", "MultiEdit", "NotebookEdit"]:
        file_path = tool_input.get("file_path", "file")
        return ClaudeStatus.editing, f"Editing {Path(file_path).name}"

    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description") or cmd
        return ClaudeStatus.running, f"Running: {desc[:40]}"

    else:
        return ClaudeStatus.busy, f"Using {tool_name}"
```

**UI Template (task_detail.html):**
```html
<div class="claude-status-section">
    <div class="status-indicator status-{{ task.claude_status.value }}">
        <span class="status-dot"></span>
        <span class="status-label">Claude: {{ task.claude_status.value }}</span>
    </div>
    {% if task.claude_activity %}
    <div class="activity-description">
        {{ task.claude_activity }}
    </div>
    {% endif %}
</div>
```

---

## Visual Design

### Status Colors

```css
.status-stopped { color: #6b7280; }     /* Gray */
.status-starting { color: #3b82f6; }    /* Blue */
.status-idle { color: #10b981; }        /* Green */
.status-thinking { color: #8b5cf6; }    /* Purple */
.status-reading { color: #06b6d4; }     /* Cyan */
.status-editing { color: #f59e0b; }     /* Amber */
.status-running { color: #ef4444; }     /* Red */
.status-waiting { color: #eab308; }     /* Yellow */
```

### Status Icons

- stopped: ⏹️
- starting: ⏳
- idle: ✅
- thinking: 💭
- reading: 📖
- editing: ✏️
- running: ⚙️
- waiting: ⏸️

---

## Benefits

1. ✅ **Clear visibility**: Users know exactly what Claude is doing
2. ✅ **Better UX**: More informative than generic "busy"
3. ✅ **Debugging**: Easier to diagnose stuck tasks
4. ✅ **Activity tracking**: See what files Claude is working on
5. ✅ **Minimal overhead**: Status derived from existing events

## Next Steps

1. Implement enhanced ClaudeStatus enum
2. Add `claude_activity` field to Task model
3. Update `_handle_event` to call `_update_status_from_event`
4. Update UI templates to show activity
5. Add CSS styling for status indicators
