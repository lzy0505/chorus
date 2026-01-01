# Chorus Documentation

Comprehensive documentation for Chorus - Task-Centric Claude Code Orchestration

## Quick Navigation

### Getting Started
- **[../README.md](../README.md)** - Quick start and installation
- **[../CLAUDE.md](../CLAUDE.md)** - Project overview and architecture
- **[../design.md](../design.md)** - Detailed technical specification
- **[../PLAN.md](../PLAN.md)** - Implementation roadmap and status

### Core Concepts

#### 📋 JSON Events
**[JSON_EVENTS.md](JSON_EVENTS.md)** - Understanding Claude Code's JSON output

Learn about the 10 event types Claude emits:
- `session_start`, `user`, `tool_use`, `tool_result`
- `text`, `assistant`, `result`, `permission_request`
- Event structure, pairing, and flow diagrams

**When to read:** Before working on event processing or monitoring

---

#### 🔄 Process Termination
**[TERMINATION_HANDLING.md](TERMINATION_HANDLING.md)** - How `-p` flag really works

Critical insights:
- `-p` exits after EACH prompt (atomic execution)
- Process termination ≠ Task completion
- Multi-step tasks need `--resume` pattern
- Detecting and handling termination

**When to read:** Before implementing task continuation or restart logic

---

#### 🔐 Permission Management
**[PERMISSION_HANDLING.md](PERMISSION_HANDLING.md)** - Non-interactive permission handling

Key concepts:
- Default behavior: `-p` blocks indefinitely (breaks tmux)
- Solution: `--allowedTools` or `--permission-mode`
- Permission profiles for different task types
- Recommended: `--permission-mode acceptEdits`

**When to read:** Before starting Claude sessions in tmux

---

#### 📊 Status Tracking
**[STATUS_TRACKING.md](STATUS_TRACKING.md)** - Granular status from events

Design proposals for:
- Enhanced status: `thinking`, `reading`, `editing`, `running`
- Activity context: "Editing main.py", "Running git status"
- UI presentation patterns
- Implementation approach

**When to read:** Before implementing status display improvements

---

## Understanding Chorus

### The Task-Centric Model

```
Task (UUID: abc-123)
  ├─ GitButler session: abc-123 (persistent)
  ├─ Tmux session: task-abc-123
  ├─ Claude session 1: xyz-111 (for --resume)
  │   ├─ Prompt: "Analyze the module"
  │   └─ Exits (stopped)
  ├─ Claude session 2: xyz-222 (resumed)
  │   ├─ Prompt: "Now implement fixes" (--resume xyz-111)
  │   └─ Exits (stopped)
  └─ User marks: Complete ✓
```

**Key Points:**
- One Task = One GitButler session (persistent)
- Multiple Claude sessions per task (via `--resume`)
- Each `-p` invocation is atomic (runs and exits)
- Task UUID used for GitButler hooks, Claude UUID for `--resume`

---

### The `-p` Pattern

**Traditional (wrong) thinking:**
```
Task created → Start Claude → Claude exits → Task done ✓
```

**Correct thinking:**
```
Task created
  → claude -p "step 1" → exits
  → claude -p "step 2" --resume <id> → exits
  → claude -p "step 3" --resume <id> → exits
  → User marks complete ✓
```

**Most of the time:** `claude_status = stopped` while `task.status = running`

This is **NORMAL**, not an error!

---

### Permission Configuration

**Without permission config (BAD):**
```bash
claude -p "fix bug" --output-format stream-json
# Claude needs to edit file → BLOCKS waiting for permission
# Process hangs indefinitely in tmux 💥
```

**With permission config (GOOD):**
```bash
claude -p "fix bug" \
  --permission-mode acceptEdits \
  --output-format stream-json
# Claude edits files → Auto-approved ✅
# Process completes and exits
```

**Chorus must ALWAYS configure permissions when starting Claude in tmux.**

---

## Architecture Overview

### Data Flow

```
User creates task in UI
  ↓
FastAPI creates Task record (UUID)
  ↓
TmuxService spawns session
  ↓
Start Claude with --output-format stream-json
  + --permission-mode acceptEdits
  + -p "initial prompt"
  ↓
JsonMonitor polls tmux output
  ↓
JsonParser extracts events
  ↓
Monitor handles events:
  - tool_use → GitButler pre-tool hook
  - tool_result → GitButler post-tool hook + commit
  - result → Extract session_id for --resume
  - Process exit → Set claude_status = stopped
  ↓
User provides next prompt
  ↓
Start Claude with --resume <session_id>
  + -p "next prompt"
  ↓
(repeat until task complete)
```

### Key Services

| Service | Responsibility |
|---------|----------------|
| `TmuxService` | Manage tmux sessions, start Claude, capture output |
| `JsonEventParser` | Parse JSON events from stream, handle line wrapping |
| `JsonMonitor` | Poll for events, update task status, trigger hooks |
| `GitButlerService` | Call GitButler hooks, discover stacks, commit changes |

---

## Common Patterns

### Starting a Task

```python
# 1. Create task with permissions
task = Task(
    title="Refactor auth module",
    permission_mode="acceptEdits",
    allowed_tools="Bash(git *:*),Read,Edit",
)
db.add(task)
db.commit()

# 2. Start Claude with permissions
tmux.start_claude_json_mode(
    task_id=task.id,
    initial_prompt="Analyze the auth module structure",
    permission_mode=task.permission_mode,
    allowed_tools=task.allowed_tools,
)

# 3. Monitor processes events automatically
# - Captures session_id from result event
# - Sets claude_status based on events
# - Calls GitButler hooks on file edits
```

### Continuing a Task

```python
# After Claude exits (claude_status = stopped)
# User provides next prompt

# Restart with --resume
tmux.start_claude_json_mode(
    task_id=task.id,
    initial_prompt="Now implement the fixes",
    resume_session_id=task.claude_session_id,  # From previous session
    permission_mode=task.permission_mode,
    allowed_tools=task.allowed_tools,
)
```

### Handling Termination

```python
# In JsonMonitor._monitor_task()
if not tmux.session_exists(task_id):
    # Claude process exited
    task.claude_status = ClaudeStatus.stopped
    task.claude_activity = None
    db.commit()
    # Stop monitoring this task
    break
```

---

## Debugging Guide

### Problem: Claude session hangs in tmux

**Likely cause:** Permission request blocking

**Check:**
1. View raw tmux output: `tmux capture-pane -p -S -`
2. Look for permission request JSON
3. Verify `--allowedTools` or `--permission-mode` was passed

**Fix:** Add permission configuration to task

---

### Problem: Task shows "stopped" immediately

**Likely cause:** Normal `-p` behavior (exits after prompt)

**Check:**
1. Was `-p` flag used? (yes = expected behavior)
2. Check `task.claude_session_id` (should be populated)
3. Look at last JSON event (should be `result` with session_id)

**Fix:** This is normal! Show "Continue" button in UI

---

### Problem: Session not resuming

**Check:**
1. `task.claude_session_id` exists in database
2. Session file exists: `~/.config/claude/<project>/sessions/<session_id>.json`
3. `--resume` flag passed when restarting

---

### Problem: Events not appearing in logs

**Check:**
1. `--output-format stream-json` flag used
2. Tmux capture getting full scrollback: `-S -`
3. JsonParser handling line wrapping correctly
4. No errors in monitor loop

---

## Next Steps

See **[../PLAN.md](../PLAN.md)** Phase 8 for upcoming features:

1. **Permission Configuration UI** - Task-scoped permission management
2. **Task Continuation UI** - Easy resumption with session context
3. **Granular Status Tracking** - Activity context ("Editing main.py")
4. **Error Detection** - Distinguish normal vs error termination

---

## Contributing

When adding features:

1. Read relevant docs first (especially if touching event handling)
2. Update docs after significant changes
3. Add examples to this README if introducing new patterns
4. Keep `PLAN.md` up to date with status

---

## Questions?

- Architecture questions: See `../design.md`
- Implementation status: See `../PLAN.md`
- Project guidelines: See `../CLAUDE.md`
- Specific topics: See individual docs above
