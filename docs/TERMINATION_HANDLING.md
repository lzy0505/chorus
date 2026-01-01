# Claude Process Termination Handling

## Termination Scenarios

### 1. Normal Completion with `-p` Flag

```bash
claude -p "fix the bug" --output-format stream-json
```

**Flow:**
1. Claude processes the prompt
2. Uses tools, generates response
3. Emits final `result` event
4. **Process exits** (non-interactive mode)
5. Tmux session terminates

**Status Updates:**
- `claude_status`: `idle` → `stopped` (process no longer running)
- `task.status`: `running` (task still active, can restart Claude)

**Key Insight:** Task is NOT complete just because Claude session ended. User may want to restart Claude to continue work.

---

### 2. Interactive Session Exit

```bash
claude --output-format stream-json
# User types commands, then exits
```

**Flow:**
1. User types `exit` or Ctrl+D
2. Claude emits `result` event (if in middle of request)
3. Process exits
4. Tmux session terminates

**Status Updates:**
- `claude_status`: `idle` → `stopped`
- `task.status`: `running` (unless user manually marks complete)

---

### 3. Crash / Error Termination

**Flow:**
1. Claude encounters error (API failure, bug, etc.)
2. May emit `error` event
3. Process crashes/exits
4. Tmux session terminates

**Status Updates:**
- `claude_status`: `busy` → `stopped` (or `error` if we detect error event)
- `task.status`: `running` (task still needs attention)

---

### 4. Permission Timeout

**Flow:**
1. Claude requests permission
2. `claude_status`: `waiting`
3. User never responds
4. Claude times out and exits
5. Tmux session terminates

**Status Updates:**
- `claude_status`: `waiting` → `stopped`
- `task.status`: `waiting` → `running` (clear permission prompt)

---

## Detecting Termination

### Current Implementation Gap

**Problem:** JSON monitor polls tmux, but doesn't update status when session disappears.

```python
# Current code in json_monitor.py
except Exception as e:
    if "not found" in str(e).lower():
        logger.info(f"Session for task {task_id} not found, stopping monitoring")
        break  # ❌ Stops monitoring but doesn't update status!
```

### Proposed Fix

**Update status when tmux session not found:**

```python
async def _monitor_task(self, task_id: UUID):
    """Monitor a specific task for JSON events."""
    logger.debug(f"Starting JSON monitoring for task {task_id}")

    while self._running:
        try:
            # Check if task still exists in database
            statement = select(Task).where(Task.id == task_id)
            task = self.db.exec(statement).first()
            if not task:
                logger.info(f"Task {task_id} no longer exists, stopping monitoring")
                break

            # Check if tmux session still exists
            if not self.tmux.session_exists(task_id):
                logger.info(f"Tmux session for task {task_id} terminated")
                # Update status to stopped
                task.claude_status = ClaudeStatus.stopped
                task.claude_activity = None
                self.db.commit()
                # Stop monitoring this task
                break

            # Capture JSON events from tmux
            output = self.tmux.capture_json_events(task_id)
            # ... rest of monitoring logic
```

---

## Status Transition Diagrams

### Non-Interactive Mode (`-p` flag)

```
[stopped]
    ↓ (start task)
[starting]
    ↓ (session_start)
[idle]
    ↓ (user event with -p)
[thinking]
    ↓ (tool_use)
[editing/reading/running]
    ↓ (tool_result)
[thinking]
    ↓ (result event)
[idle]
    ↓ (process exits)
[stopped] ← Task still "running", can restart Claude
```

### Interactive Mode

```
[stopped]
    ↓ (start task)
[starting]
    ↓ (session_start)
[idle] ←─────────────┐
    ↓                │
[thinking]           │
    ↓                │
[editing/running]    │
    ↓                │
[idle] ──────────────┘
    ↓ (user types exit)
[stopped] ← Task still "running", can restart Claude
```

### Error/Crash

```
[any status]
    ↓ (error/crash)
[stopped]
```

---

## Task Status vs Claude Status

**Key Distinction:**

| Status | Meaning | Controls |
|--------|---------|----------|
| `task.status` | Overall task state | Whether task is pending/running/completed/failed |
| `task.claude_status` | Claude process state | Whether Claude is running in tmux |

**Example Lifecycle:**

```
Task Created:
  task.status = pending
  claude_status = stopped

User Starts Task:
  task.status = running
  claude_status = starting → idle

Claude Works:
  task.status = running
  claude_status = editing/reading/thinking

Claude -p Exits:
  task.status = running (STILL RUNNING!)
  claude_status = stopped

User Restarts Claude:
  task.status = running
  claude_status = starting → idle
  (uses --resume with previous session_id)

User Marks Complete:
  task.status = completed
  claude_status = stopped
```

---

## Restart Behavior

When `claude_status = stopped` but `task.status = running`:

**Restart Options:**

1. **Resume Previous Session:**
   ```bash
   claude --resume {task.claude_session_id} --output-format stream-json
   ```
   - Continues previous conversation context
   - Used when Claude was making progress

2. **Fresh Session with Context:**
   ```bash
   claude --append-system-prompt "$(cat context.txt)" --output-format stream-json
   ```
   - New session, but with task context
   - Used when previous session was stuck/errored

3. **Prompt-Based Restart:**
   ```bash
   claude -p "Continue working on this task" --output-format stream-json
   ```
   - Non-interactive, runs and exits
   - Good for automated workflows

---

## UI Presentation

### When Claude Process Stopped

```
┌─────────────────────────────────────────┐
│ Task: Update README                      │
│ Status: running                          │
│                                          │
│ Claude: stopped 🔴                       │
│ └─ Process exited                        │
│                                          │
│ Last Activity:                           │
│ • 14:25:10 Completed request            │
│ • 14:25:05 Edited README.md             │
│                                          │
│ [Restart Claude] [Complete Task]         │
└─────────────────────────────────────────┘
```

### When Task Completed but Claude Running

```
┌─────────────────────────────────────────┐
│ Task: Update README                      │
│ Status: completed ✓                      │
│                                          │
│ Claude: idle ⚪                           │
│ └─ Session still active                  │
│                                          │
│ [Stop Claude] [Delete Task]              │
└─────────────────────────────────────────┘
```

---

## Implementation Checklist

- [ ] Add `session_exists()` check in monitor loop
- [ ] Update `claude_status` to `stopped` when session ends
- [ ] Clear `claude_activity` on termination
- [ ] Distinguish normal exit from crash in logs
- [ ] Add UI indicator for "Claude stopped, task running"
- [ ] Test restart behavior with `--resume`
- [ ] Handle edge case: task deleted while Claude running

---

## Summary

**Answer:** When `claude -p` terminates:

1. **Set `claude_status = stopped`** (process no longer running)
2. **Keep `task.status = running`** (task may need more work)
3. **Clear `claude_activity`** (no active operation)
4. **Allow restart** (user can resume or start fresh)

This separates the **ephemeral Claude process** from the **persistent task state**.
