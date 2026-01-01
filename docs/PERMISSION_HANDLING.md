# Permission Handling in Claude Code with `-p` Flag

## The Problem

When running `claude -p` non-interactively in tmux:
- Claude may need permission for dangerous operations (e.g., `rm -rf`, file edits)
- **By default, the process BLOCKS** waiting for user input
- In tmux/headless sessions, this causes the process to hang indefinitely
- No automatic approval or denial happens

## Solutions

### 1. Pre-Approve Tools with `--allowedTools`

**Recommended for Chorus.** Explicitly list which tools Claude can use without prompting:

```bash
claude -p "Fix the authentication bug" \
  --allowedTools "Bash,Read,Edit,Grep,Glob" \
  --output-format stream-json
```

**Allow specific Bash commands (granular control):**

```bash
claude -p "Create a git commit for the changes" \
  --allowedTools "Bash(git status:*),Bash(git diff:*),Bash(git add:*),Bash(git commit:*),Read,Edit" \
  --output-format stream-json
```

**Pattern syntax:**
- `"Bash"` — Allow all Bash commands
- `"Bash(git *:*)"` — Allow all git commands
- `"Bash(git status:*)"` — Allow only `git status`
- `"Read,Edit,Write"` — Allow multiple tools (comma-separated)

---

### 2. Use Permission Modes

The `--permission-mode` flag changes permission behavior:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `default` | Prompts for permission (BLOCKS in `-p` mode) | Interactive use only |
| `acceptEdits` | Auto-accepts all file edits for the session | Safe when you trust Claude with file modifications |
| `plan` | Read-only mode (no edits, no bash) | Safe initial analysis before modifications |
| `bypassPermissions` | Skips ALL permission prompts | **Dangerous** - only in trusted environments |

**Example - Auto-accept file edits:**
```bash
claude -p "Refactor the auth module" \
  --permission-mode acceptEdits \
  --output-format stream-json
```

**Example - Read-only analysis first:**
```bash
# Step 1: Analyze (safe, read-only)
claude -p "Analyze security issues in auth.py" \
  --permission-mode plan \
  --output-format stream-json

# Step 2: Implement fixes (after review, allow edits)
claude -p "Now implement the fixes" \
  --resume <session_id> \
  --permission-mode acceptEdits \
  --output-format stream-json
```

---

### 3. PermissionRequest Hook (Advanced)

For complex permission logic, use hooks to intercept permission requests:

**Hook configuration (`.claude/settings.json`):**
```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/chorus-permission-handler.py"
          }
        ]
      }
    ]
  }
}
```

**Hook script receives JSON input:**
```json
{
  "toolName": "Bash",
  "toolInput": {
    "command": "rm -rf /tmp/build"
  }
}
```

**Hook responds with decision:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow"  // or "deny"
    }
  }
}
```

**Use cases:**
- Check against task-specific allowed commands (stored in Chorus DB)
- Log permission requests for auditing
- Dynamically approve based on task configuration
- Deny destructive operations unless explicitly allowed

---

## Chorus Implementation Strategy

### Recommended Approach: Task-Scoped Permissions

Store allowed tools per task in the database:

```python
class Task(SQLModel, table=True):
    ...
    allowed_tools: Optional[str] = Field(default=None)  # e.g., "Bash,Read,Edit"
    permission_mode: str = Field(default="default")     # acceptEdits, plan, bypassPermissions
```

When starting Claude:

```python
def start_claude_json_mode(
    self,
    task_id: UUID,
    initial_prompt: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    permission_mode: str = "default",
) -> None:
    """Start Claude with task-specific permissions."""

    # Build command with permissions
    cmd_parts = ["claude", "--output-format", "stream-json", "--verbose"]

    # Add permission configuration
    if permission_mode != "default":
        cmd_parts.extend(["--permission-mode", permission_mode])

    if allowed_tools:
        cmd_parts.extend(["--allowedTools", allowed_tools])

    if initial_prompt:
        cmd_parts.extend(["-p", f'"{initial_prompt}"'])

    # Execute in tmux
    cmd = " ".join(cmd_parts)
    # ... tmux setup
```

### Default Permission Profiles

Create presets for common task types:

```python
PERMISSION_PROFILES = {
    "read_only": {
        "allowed_tools": "Read,Grep,Glob,LSP",
        "permission_mode": "plan",
    },
    "safe_edit": {
        "allowed_tools": "Read,Edit,Write,Grep,Glob",
        "permission_mode": "acceptEdits",
    },
    "full_dev": {
        "allowed_tools": "Bash,Read,Edit,Write,Grep,Glob,LSP",
        "permission_mode": "acceptEdits",
    },
    "git_only": {
        "allowed_tools": "Bash(git *:*),Read,Grep",
        "permission_mode": "default",
    },
}

# When creating task:
task = Task(
    title="Refactor auth module",
    allowed_tools=PERMISSION_PROFILES["safe_edit"]["allowed_tools"],
    permission_mode=PERMISSION_PROFILES["safe_edit"]["permission_mode"],
)
```

### UI for Permission Configuration

```
┌─────────────────────────────────────────┐
│ Create New Task                          │
│                                          │
│ Title: Refactor authentication module   │
│                                          │
│ Permission Profile:                      │
│ ○ Read-only (analysis)                   │
│ ● Safe Edit (read + file edits)          │
│ ○ Full Dev (bash + edits)                │
│ ○ Custom                                  │
│                                          │
│ ✓ Auto-accept file edits                 │
│ ✓ Allow git commands                     │
│ □ Allow npm commands                      │
│ □ Bypass all permissions (dangerous)     │
│                                          │
│ [Create Task]                            │
└─────────────────────────────────────────┘
```

---

## What Happens in Each Mode

### Scenario: Claude wants to run `rm -rf /tmp/build`

| Configuration | Behavior |
|---------------|----------|
| No flags (default) | **BLOCKS** - Process hangs waiting for stdin input |
| `--allowedTools "Bash"` | ✅ Auto-approves - Command runs immediately |
| `--allowedTools "Bash(git *:*)"` | **BLOCKS** - `rm` not in allowed patterns |
| `--permission-mode acceptEdits` | **BLOCKS** - Only file edits auto-approved, not Bash |
| `--permission-mode bypassPermissions` | ✅ Auto-approves - ALL tools allowed (dangerous) |
| PermissionRequest hook | ✅ or ❌ - Hook decides programmatically |

### Scenario: Claude wants to edit `auth.py`

| Configuration | Behavior |
|---------------|----------|
| No flags (default) | **BLOCKS** - Process hangs |
| `--allowedTools "Edit"` | ✅ Auto-approves |
| `--permission-mode acceptEdits` | ✅ Auto-approves |
| `--permission-mode plan` | ❌ **Denies** - Read-only mode |

---

## JSON Event Flow with Permissions

### When Permission is Granted (no blocking):

```json
{"type": "tool_use", "toolName": "Edit", "toolInput": {...}}
{"type": "tool_result", "isError": false, "content": "..."}
```

### When Permission is Denied (blocks in default mode):

**With `--permission-mode plan` (auto-deny):**
```json
{"type": "tool_use", "toolName": "Edit", "toolInput": {...}}
{"type": "tool_result", "isError": true, "content": "Permission denied: plan mode is read-only"}
```

**With default mode (BLOCKS - no events emitted until user responds):**
```json
{"type": "tool_use", "toolName": "Edit", "toolInput": {...}}
# Process hangs here waiting for stdin input
# No further events until permission granted/denied via stdin
```

---

## Recommendations for Chorus

1. **Always use `--allowedTools` or `--permission-mode` when starting tasks**
   - Never rely on default blocking behavior in tmux
   - Configure permissions at task creation time

2. **Default to `--permission-mode acceptEdits` for most tasks**
   - Safe for file modifications
   - Still prompts for dangerous Bash commands
   - Good balance of safety and automation

3. **For read-only analysis, use `--permission-mode plan`**
   - First step in multi-step tasks
   - Safe exploration before modifications

4. **Store permission config in Task model**
   - User selects at task creation
   - Persists across Claude restarts
   - Easy to audit and modify

5. **Consider PermissionRequest hook for advanced cases**
   - Dynamic approval based on task context
   - Logging and auditing
   - Integration with external approval systems

6. **Show permission status in UI**
   - Display active permission mode
   - Show allowed tools
   - Warn when bypassing permissions

---

## Implementation Checklist

- [ ] Add `allowed_tools` field to Task model
- [ ] Add `permission_mode` field to Task model
- [ ] Create permission profile presets
- [ ] Update `start_claude_json_mode()` to include permission flags
- [ ] Add permission configuration UI to task creation
- [ ] Document permission profiles in CLAUDE.md
- [ ] Consider PermissionRequest hook for advanced scenarios
- [ ] Add permission status to task detail view

---

## See Also

- Claude Code CLI Reference: https://code.claude.com/docs/en/cli-reference.md
- Hooks Reference: https://code.claude.com/docs/en/hooks.md
- Agent SDK (for programmatic control): https://platform.claude.com/docs/en/agent-sdk/overview
