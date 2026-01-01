# Claude Process Termination Handling

## Termination Scenarios

### 1. Normal Completion with `-p` Flag (SDK Mode)

```bash
claude -p "fix the bug" --output-format stream-json
```

**Flow:**
1. Claude processes the prompt
2. Uses tools, generates response
3. Emits final `result` event with `session_id`
4. **Process exits** (non-interactive mode - `-p` is atomic)
5. Tmux session terminates

**Status Updates:**
- `claude_status`: `idle` → `stopped` (process no longer running)
- `task.status`: `running` (task still active, needs continuation)
- `task.claude_session_id`: Captured from `result` event for resumption

**Critical Understanding:**
- ✅ **The `-p` invocation is complete** (that specific prompt was processed)
- ❌ **The TASK is NOT complete** (may need multiple `-p` invocations to finish)
- 🔄 **Resumption is the pattern** for multi-step tasks

**Multi-Step Task Pattern:**
```bash
# Step 1: Initial analysis
claude -p "Analyze the authentication module" --output-format stream-json
# → exits, session_id saved to task.claude_session_id

# Step 2: Resume to implement (SAME session, builds on analysis)
claude -p "Now implement the fixes based on your analysis" \
  --resume <session_id> --output-format stream-json
# → exits, session_id remains same

# Step 3: Resume to verify
claude -p "Run tests to verify the fixes" \
  --resume <session_id> --output-format stream-json
# → exits, TASK NOW COMPLETE (user marks task complete)
```

**Key Insight:** `-p` termination means "this prompt is done", NOT "task is done". Tasks often require multiple resumed `-p` invocations to fully complete.

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

## Continuation Patterns

When `claude_status = stopped` but `task.status = running`:

### Recommended: Resume with New Prompt (Multi-Step Tasks)

```bash
claude -p "Continue: now implement the fixes" \
  --resume {task.claude_session_id} \
  --output-format stream-json
```

**Use when:**
- ✅ Task requires multiple steps (analyze → implement → test)
- ✅ Claude needs context from previous work
- ✅ Building on prior tool usage and findings
- ✅ Normal `-p` termination (not error/crash)

**Benefits:**
- Claude remembers files read, patterns found, previous analysis
- Session history maintains coherent conversation
- Each `-p` invocation is atomic and predictable

### Alternative: Resume Interactive

```bash
claude --resume {task.claude_session_id} --output-format stream-json
```

**Use when:**
- User wants to interactively guide Claude
- Task direction unclear, needs back-and-forth
- Debugging or exploratory work

**Note:** Session stays open until user exits (not atomic like `-p`)

### Last Resort: Fresh Session

```bash
claude -p "Start fresh: analyze the auth module" \
  --output-format stream-json
```

**ONLY use when:**
- ❌ Previous session crashed or got stuck
- ❌ Want to discard all prior context
- ❌ Starting completely different work

**Downside:** Loses all previous context, Claude starts from scratch

---

## UI Presentation

### When Claude Process Stopped (Task Incomplete)

```
┌─────────────────────────────────────────┐
│ Task: Update README                      │
│ Status: running ⚠️ Needs continuation    │
│                                          │
│ Claude: stopped 🔴                       │
│ └─ Prompt completed, session preserved  │
│                                          │
│ Session: abc123... (can resume)         │
│                                          │
│ Last Activity:                           │
│ • 14:25:10 ✓ Completed initial analysis │
│ • 14:25:05 📖 Read 3 files              │
│ • 14:24:50 💭 Analyzing structure       │
│                                          │
│ Next Steps:                              │
│ [Continue with -p] ← Recommended         │
│ [Resume Interactive]                     │
│ [Start Fresh]                            │
│ [Mark Complete]                          │
└─────────────────────────────────────────┘
```

**"Continue with -p" button:**
- Shows input field for next prompt
- Runs: `claude -p "<user prompt>" --resume <session_id> --output-format stream-json`
- Preserves conversation context
- Exits when done (atomic)

**Example flow:**
```
User creates task: "Refactor auth module"
├─ Start: claude -p "Analyze auth module" → exits
├─ Continue: claude -p "Now implement fixes" --resume → exits
├─ Continue: claude -p "Run tests" --resume → exits
└─ User marks: Complete ✓
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
2. **Keep `task.status = running`** (task almost certainly needs more work)
3. **Preserve `claude_session_id`** (CRITICAL for resumption)
4. **Clear `claude_activity`** (no active operation)
5. **Show continuation UI** (prompt user to continue with `-p --resume`)

This separates the **ephemeral Claude process** from the **persistent task state**.

---

## Key Takeaways for Chorus Implementation

### 1. `-p` Termination is NORMAL, Not Completion

```
❌ OLD THINKING: "Claude exited → task is done"
✅ NEW THINKING: "Claude finished this step → user provides next prompt"
```

### 2. Session ID is the Continuity Anchor

```python
# When task starts:
task.claude_session_id = None

# After first -p completes:
task.claude_session_id = "abc123..."  # SAVE THIS!

# On subsequent continuations:
cmd = f"claude -p '{next_prompt}' --resume {task.claude_session_id}"
```

### 3. Default Action: Resume, Not Restart

**UI should default to "Continue" button that:**
- Prompts user for next instruction
- Uses `--resume` with saved session_id
- Runs with `-p` for atomic execution
- Exits and waits for next continuation

**NOT:**
- ❌ Auto-restart fresh session (loses context)
- ❌ Auto-mark complete (task likely incomplete)
- ❌ Require manual session ID entry (should be automatic)

### 4. Task Lifecycle with `-p` Pattern

```
Task Created (pending)
  ↓
User starts with prompt
  ↓
Claude -p runs → exits (stopped)
  ↓
User continues with new prompt
  ↓
Claude -p --resume runs → exits (stopped)
  ↓
User continues again...
  ↓
... (multiple iterations)
  ↓
User manually marks complete
```

**Notice:** Most of the time, `claude_status = stopped` while `task.status = running`. This is the NORMAL state, not an error condition.

### 5. Implementation Checklist

- [x] Detect tmux termination
- [x] Set `claude_status = stopped` on termination
- [x] Preserve `claude_session_id` in database
- [ ] Add "Continue" button to UI (default action when stopped)
- [ ] Input field for next prompt on continue
- [ ] Auto-populate `--resume` flag with saved session_id
- [ ] Show session ID in UI for debugging
- [ ] Track continuation count (how many `-p` invocations)
- [ ] Show prompt history (each `-p` prompt used)

### 6. Error vs Normal Termination

**Normal termination (most common):**
- Last event: `result` with `stopReason: "end_turn"`
- Session ID present
- No error events
- Action: Offer to continue

**Error termination:**
- Last event: `error` or `result` with error
- May or may not have session ID
- Action: Offer to start fresh OR resume if session exists

**User cancellation:**
- Tmux session killed manually
- No final `result` event
- Action: Offer to start fresh (context lost)
