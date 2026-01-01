# Interactive Permission Handling in Tmux

## The Realization

**We don't need to bypass permissions!** Tmux is an interactive terminal - we can:
1. Let Claude ask for permission normally
2. Capture the permission request via JSON events
3. Show UI to user
4. Send response ('y' or 'n') back to tmux
5. Claude continues processing

## Why This is Better Than Pre-Approval

### Current Approach (Pre-Approval)
```bash
claude -p "fix bugs" \
  --allowedTools "Bash,Edit" \
  --output-format stream-json
```

**Problems:**
- ❌ Blindly approves ALL Bash commands
- ❌ No visibility into what Claude is doing
- ❌ Can't prevent dangerous operations
- ❌ User has no control

### Interactive Approach
```bash
claude -p "fix bugs" \
  --output-format stream-json
# NO permission flags!
```

**Benefits:**
- ✅ See exactly what Claude wants to do
- ✅ Approve/deny each operation individually
- ✅ Prevent dangerous commands (`rm -rf`, etc.)
- ✅ Better security and control
- ✅ User stays informed

---

## How It Works

### 1. Claude Emits Permission Request

**JSON Event:**
```json
{
  "type": "permission_request",
  "prompt": "Allow Claude to execute 'git commit -m \"Fix auth bug\"'?"
}
```

**What happens:**
- Claude blocks waiting for stdin input ('y' or 'n')
- Process doesn't exit, just waits
- JSON stream continues flowing

### 2. JsonMonitor Detects Request

```python
case "permission_request":
    task.status = TaskStatus.waiting
    task.claude_status = ClaudeStatus.waiting
    prompt = event.data.get("prompt", "Permission requested")
    task.permission_prompt = prompt
    db.commit()
```

**Updates:**
- Task status → `waiting`
- Permission prompt stored in DB
- UI automatically updates via SSE

### 3. UI Shows Permission Dialog

**Already implemented in `task_detail.html`:**
```html
{% if task.permission_prompt %}
<div class="permission-box">
    <div class="permission-prompt">
        <strong>⚠️ Permission Required:</strong><br>
        {{ task.permission_prompt }}
    </div>
    <div class="permission-actions">
        <button hx-post="/dashboard/tasks/{{ task.id }}/respond?confirm=true">
            ✓ Approve
        </button>
        <button hx-post="/dashboard/tasks/{{ task.id }}/respond?confirm=false">
            ✗ Deny
        </button>
    </div>
</div>
{% endif %}
```

### 4. User Clicks Approve/Deny

**Endpoint:** `/dashboard/tasks/{task_id}/respond`

```python
def respond_to_permission(task_id: UUID, confirm: bool):
    tmux.send_confirmation(task_id, confirm)
    task.permission_prompt = None
    db.commit()
```

### 5. Tmux Sends Response to Claude

**In `tmux.py`:**
```python
def send_confirmation(self, task_id: UUID, confirm: bool):
    """Respond to permission prompt."""
    response = "y" if confirm else "n"
    self.send_keys(task_id, response)  # Sends to tmux stdin
```

**Tmux command executed:**
```bash
tmux send-keys -t task-{uuid} "y" Enter
# or
tmux send-keys -t task-{uuid} "n" Enter
```

### 6. Claude Receives Response

- Claude reads 'y' or 'n' from stdin
- Continues execution based on response
- Emits `tool_use` event if approved
- Emits error/denial if rejected

---

## Complete Flow Example

```
User: "Fix the authentication bug"
  ↓
Claude analyzes code
  ↓
Claude: "I need to edit auth.py"
  ↓
JSON: {"type": "permission_request", "prompt": "Edit auth.py?"}
  ↓
Monitor: Sets task.status = waiting, stores prompt
  ↓
UI: Shows permission dialog to user
  ↓
User: Clicks "✓ Approve"
  ↓
API: Calls tmux.send_confirmation(task_id, True)
  ↓
Tmux: Sends "y\n" to Claude's stdin
  ↓
Claude: Receives approval, proceeds with edit
  ↓
JSON: {"type": "tool_use", "toolName": "Edit", ...}
  ↓
Monitor: Calls GitButler hooks, commits change
  ↓
Task continues...
```

---

## Hybrid Approach (Best of Both Worlds)

We can support BOTH patterns:

### Option 1: Interactive (Default)
```python
task = Task(
    title="Fix bug",
    permission_mode="default",  # Ask for each operation
)
```

**Use when:**
- User wants control
- Reviewing changes carefully
- Learning what Claude does
- Security-critical operations

### Option 2: Auto-Approve Safe Operations
```python
task = Task(
    title="Refactor code",
    permission_mode="acceptEdits",  # Auto-approve file edits only
    allowed_tools=None,             # But ask for Bash commands
)
```

**Use when:**
- Trust Claude with file edits
- Still want to review bash commands
- Balance between speed and control

### Option 3: Full Auto (Use Sparingly)
```python
task = Task(
    title="Run tests and commit",
    permission_mode="acceptEdits",
    allowed_tools="Bash(git *:*),Read,Edit",  # Pre-approve git commands
)
```

**Use when:**
- Fully automated workflows
- Safe, well-defined operations
- High trust environment

---

## Implementation Status

### ✅ Already Working!
- [x] `permission_request` event detection
- [x] Store prompt in `task.permission_prompt`
- [x] UI shows permission dialog
- [x] Approve/Deny buttons
- [x] `/respond` endpoint
- [x] `send_confirmation()` method
- [x] Status updates (waiting → running)

### 🔄 Enhancements Needed
- [ ] Show what tool Claude wants to use in UI
- [ ] Show full tool input (not just prompt text)
- [ ] "Remember this decision" checkbox
- [ ] Per-tool permission policies
- [ ] Permission history log

---

## Enhanced UI Mockup

```
┌─────────────────────────────────────────────────────┐
│ ⚠️ Claude Needs Permission                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Tool: Bash                                          │
│ Command: git commit -m "Fix authentication bug"    │
│                                                     │
│ Description: Creating a git commit with changes    │
│                                                     │
│ Risk Level: 🟡 Medium                               │
│ - Modifies git history                             │
│ - Cannot be undone without git reset               │
│                                                     │
│ Files affected:                                     │
│ • auth.py (modified)                               │
│ • tests/test_auth.py (modified)                    │
│                                                     │
│ ☐ Remember this decision for:                      │
│   ○ This session                                    │
│   ○ This task                                       │
│   ○ All tasks                                       │
│                                                     │
│ [✓ Approve]  [✗ Deny]  [🔍 Show Details]           │
└─────────────────────────────────────────────────────┘
```

---

## Advanced: Per-Tool Policies

Store permission policies in task configuration:

```python
class Task:
    permission_policy: Optional[dict] = Field(default=None)
    # Example:
    # {
    #   "Edit": "always_allow",
    #   "Write": "always_allow",
    #   "Bash": "ask",
    #   "Bash(git commit:*)": "always_allow",
    #   "Bash(rm:*)": "always_deny"
    # }
```

**Decision logic:**
```python
def should_auto_approve(tool_name: str, tool_input: dict, policy: dict) -> bool:
    # Check specific pattern first
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        for pattern, action in policy.items():
            if pattern.startswith("Bash(") and matches_pattern(cmd, pattern):
                return action == "always_allow"

    # Check tool-level policy
    action = policy.get(tool_name, "ask")
    return action == "always_allow"
```

---

## Security Considerations

### Dangerous Operations to Always Ask

Even with auto-approval, ALWAYS ask for:
- `rm -rf` or recursive deletions
- `sudo` commands
- Network operations (curl, wget to unknown domains)
- Database modifications (DROP, DELETE without WHERE)
- File operations outside project directory

### Safe Operations to Auto-Approve

- Git commands (status, diff, log, commit, push)
- Test runners (pytest, npm test)
- Linters (eslint, black, ruff)
- File reads within project
- File edits within project

---

## Recommendation

**Default behavior for Chorus:**

1. **Start with interactive mode** (no permission flags)
2. **Show rich permission UI** with tool details
3. **Let user configure per-task** (interactive vs auto-approve)
4. **Remember decisions** within session/task
5. **Always ask for dangerous operations** regardless of config

This gives:
- ✅ Maximum visibility and control
- ✅ Flexibility for different workflows
- ✅ Security by default
- ✅ Speed when needed (via auto-approve)

---

## Next Steps

1. **Enhance permission UI** - Show tool details, risk level
2. **Add "remember" functionality** - Store decisions
3. **Implement per-tool policies** - Fine-grained control
4. **Add permission history** - Audit log
5. **Default to interactive** - Remove `--permission-mode acceptEdits` from default

The infrastructure is already there - we just need to embrace it!
