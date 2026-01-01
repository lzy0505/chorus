# Task-Specific Permission Hooks with PermissionRequest

## Overview

Chorus implements **per-task permission policies** using Claude Code's `PermissionRequest` hooks. Each task has its own isolated Claude configuration directory, ensuring permissions don't pollute the global `~/.claude` config.

**Key Features:**
- ✅ Task-specific permission policies stored in database
- ✅ **Strong isolation via `CLAUDE_CONFIG_DIR`** - no cross-task contamination
- ✅ Predefined permission profiles (read_only, safe_edit, full_dev, git_only)
- ✅ Works with `-p` flag (non-interactive mode)
- ✅ Programmatic allow/deny decisions
- ✅ File pattern and bash command filtering
- ✅ Audit logging via stderr

## Isolation Guarantees

**Critical Security Feature:** Each task's permission policy is completely isolated:

1. **Task ID derived from `CLAUDE_CONFIG_DIR`** - Not from hook input (which could be spoofed)
2. **Separate config directories** - Each task has `/tmp/chorus/config/task-{uuid}/.claude/`
3. **Environment-based isolation** - Claude sets `CLAUDE_CONFIG_DIR` per process
4. **Database lookup per task** - Permission handler queries DB using extracted task UUID
5. **No global config pollution** - Tasks never touch `~/.claude/`

**Verification:** Run `/tmp/verify_permission_isolation.sh` to verify isolation

---

## Architecture

### Directory Structure

```
/tmp/chorus/
  hooks/
    permission-handler.py         # Shared handler script (queries DB)
  config/
    task-{uuid-1}/
      .claude/
        settings.json             # PermissionRequest hook config
    task-{uuid-2}/
      .claude/
        settings.json             # Different policy!
```

### Data Flow

```
1. Task Created
   ├─ User selects permission profile (UI dropdown)
   ├─ Profile → Permission policy JSON
   └─ Saved to task.permission_policy (database)

2. Task Started
   ├─ Create task-specific config dir: /tmp/chorus/config/task-{uuid}
   ├─ Write settings.json with PermissionRequest hook
   └─ Start Claude with CLAUDE_CONFIG_DIR=/tmp/chorus/config/task-{uuid}

3. Claude Uses Tool
   ├─ PermissionRequest hook triggered
   ├─ Handler reads task.permission_policy from DB (using session_id = task.id)
   ├─ Evaluates tool/file/command against policy
   └─ Returns {"behavior": "allow"} or {"behavior": "deny"}

4. Task Deleted
   └─ Cleanup config directory (shutil.rmtree)
```

---

## Permission Policy Format

Permission policies are stored as JSON in the `task.permission_policy` database field:

```json
{
  "allowed_tools": [
    "Read", "Edit", "Write", "Grep", "Glob", "LSP"
  ],
  "bash_patterns": {
    "allow": [
      "^git status",
      "^git diff",
      "^npm test"
    ],
    "deny": [
      "rm -rf /",
      "sudo",
      "DROP TABLE"
    ]
  },
  "file_patterns": {
    "allow": [
      "*.py",
      "*.md",
      "*.json"
    ],
    "deny": [
      ".env",
      ".git/*",
      "*.key"
    ]
  },
  "auto_approve": true
}
```

### Policy Evaluation Order

1. **Tool Allowlist** (`allowed_tools`): If set, tool must be in list
2. **Deny Patterns**: Check deny patterns first (highest priority)
3. **Allow Patterns**: Check allow patterns
4. **Auto-Approve**: If enabled, allow anything not explicitly denied
5. **Default**: Let normal permission flow proceed (prompt user)

---

## Predefined Permission Profiles

### `read_only`
```json
{
  "allowed_tools": ["Read", "Grep", "Glob", "LSP"],
  "bash_patterns": {
    "allow": ["^ls", "^pwd", "^cat"],
    "deny": [".*"]
  },
  "auto_approve": true
}
```
**Use case:** Code analysis, documentation review

### `safe_edit`
```json
{
  "allowed_tools": ["Read", "Edit", "Write", "Grep", "Glob", "LSP"],
  "bash_patterns": {
    "allow": ["^git status", "^git diff", "^git log"],
    "deny": [".*"]  // Block all other bash
  },
  "file_patterns": {
    "allow": ["*.py", "*.js", "*.md", "*.json"],
    "deny": [".env", ".git/*", "*.key"]
  },
  "auto_approve": true
}
```
**Use case:** File editing without bash access

### `full_dev` (Default)
```json
{
  "allowed_tools": ["Read", "Edit", "Write", "Grep", "Glob", "LSP"],
  "bash_patterns": {
    "allow": [
      "^git ", "^npm test", "^pytest", "^ls", "^pwd"
    ],
    "deny": [
      "rm -rf /", "sudo", "DROP TABLE"
    ]
  },
  "file_patterns": {
    "allow": ["*.py", "*.js", "*.ts", "*.md", "*.json"],
    "deny": [".env", ".git/*", "secrets.json", "*.key"]
  },
  "auto_approve": true
}
```
**Use case:** General development tasks

### `git_only`
```json
{
  "allowed_tools": ["Read", "Grep", "Glob"],
  "bash_patterns": {
    "allow": ["^git "],
    "deny": []
  },
  "auto_approve": true
}
```
**Use case:** Git repository analysis

---

## Implementation Details

### 1. Task Model (`models.py`)

```python
class Task(SQLModel, table=True):
    # ... other fields ...
    permission_policy: str = Field(default="")  # JSON permission policy
```

### 2. Claude Config Service (`services/claude_config.py`)

```python
def create_task_claude_config(task_id: UUID, permission_policy: Optional[Dict] = None) -> Path:
    """Create task-specific Claude config with PermissionRequest hook."""
    config_dir = Path(f"/tmp/chorus/config/task-{task_id}")
    settings = {
        "hooks": {
            "PermissionRequest": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": "/tmp/chorus/hooks/permission-handler.py",
                    "timeout": 10
                }]
            }]
        }
    }
    # Write settings.json to config_dir/.claude/
    return config_dir
```

### 3. Permission Handler (`/tmp/chorus/hooks/permission-handler.py`)

**Input (via stdin):**
```json
{
  "session_id": "task-uuid",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /"},
  "hook_event_name": "PermissionRequest"
}
```

**Output (to stdout):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "deny",
      "message": "Command blocked by policy: matches pattern 'rm -rf /'"
    }
  }
}
```

**Environment Variables:**
- `CHORUS_DB_PATH`: Path to Chorus database (set by tmux service)
- `CLAUDE_CONFIG_DIR`: Task-specific config directory (set by tmux service)

### 4. Tmux Service Integration (`services/tmux.py`)

```python
def start_claude_json_mode(task_id, ...):
    # Set task-specific config directory
    task_config_dir = get_task_config_dir(task_id)
    env_vars = [
        f'CLAUDE_CONFIG_DIR="{task_config_dir}"',
        f'CHORUS_DB_PATH="{db_path}"',
    ]

    # Start Claude with environment variables
    claude_cmd = f'{" ".join(env_vars)} claude --output-format stream-json ...'
```

### 5. Task Creation API (`api/tasks.py`)

```python
@router.post("")
async def create_task(task_data: TaskCreate, db: Session):
    # Get permission policy from profile
    policy = get_permission_profile(task_data.permission_profile)

    task = Task(
        title=task_data.title,
        permission_policy=json.dumps(policy),
    )
    db.add(task)
    db.commit()
```

### 6. Task Start Endpoint

```python
@router.post("/{task_id}/start")
async def start_task(task_id: UUID, ...):
    # Create task-specific Claude config
    policy = json.loads(task.permission_policy)
    create_task_claude_config(task_id, permission_policy=policy)

    # Start Claude (CLAUDE_CONFIG_DIR env var set in tmux service)
    tmux.start_claude_json_mode(task_id, ...)
```

---

## UI Integration

### Task Creation Form

```html
<select name="permission_profile">
  <option value="full_dev" selected>Full Dev (recommended)</option>
  <option value="safe_edit">Safe Edit (read + file edits)</option>
  <option value="read_only">Read Only (analysis)</option>
  <option value="git_only">Git Only</option>
</select>
```

User selects profile → API converts to policy JSON → Stored in database

---

## Testing

### Manual Test

```bash
# 1. Create task with safe_edit profile
curl -X POST http://localhost:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Test","permission_profile":"safe_edit"}'

# 2. Start task
curl -X POST http://localhost:8000/api/tasks/{task_id}/start

# 3. Verify config created
ls /tmp/chorus/config/task-{task_id}/.claude/settings.json

# 4. Test permission handler directly
echo '{"session_id":"task-uuid","tool_name":"Bash","tool_input":{"command":"rm -rf /"},"hook_event_name":"PermissionRequest"}' | \
  CHORUS_DB_PATH=/path/to/orchestrator.db \
  /tmp/chorus/hooks/permission-handler.py
```

### Expected Behavior

**Allowed operations (safe_edit profile):**
- ✅ Read Python/JS/MD files
- ✅ Edit Python/JS/MD files
- ✅ `git status`, `git diff`

**Denied operations:**
- ❌ Edit `.env` files
- ❌ `rm -rf /`
- ❌ `sudo` commands
- ❌ Bash commands (except git)

---

## Advantages Over `--permission-mode acceptEdits`

| Feature | acceptEdits | PermissionRequest Hooks |
|---------|-------------|------------------------|
| Per-task policies | ❌ Global | ✅ Task-specific |
| Granular control | ❌ All edits | ✅ Pattern-based |
| Command filtering | ❌ No | ✅ Regex patterns |
| File filtering | ❌ No | ✅ Glob patterns |
| Audit logging | ❌ No | ✅ Full logging |
| Dynamic decisions | ❌ Static | ✅ Database-driven |
| Bash control | ❌ Prompts | ✅ Auto allow/deny |

---

## Debugging

### Enable Debug Logging

Set `level = "DEBUG"` in `chorus.toml` to see detailed permission decisions:

```
[permission-handler] Received input: tool=Bash, session=abc-123
[permission-handler] Loaded policy for task abc-123: {...}
[permission-handler] Command blocked: matches pattern 'rm -rf /'
[permission-handler] Decision: deny
```

### Check Task Config

```bash
# View task's settings.json
cat /tmp/chorus/config/task-{uuid}/.claude/settings.json

# View task's permission policy
sqlite3 orchestrator.db \
  "SELECT permission_policy FROM task WHERE id='{uuid-without-dashes}'"
```

### Test Handler in Isolation

```bash
# Test with fake input
echo '{"session_id":"test","tool_name":"Bash","tool_input":{"command":"test"},"hook_event_name":"PermissionRequest"}' | \
  CHORUS_DB_PATH=/path/to/db /tmp/chorus/hooks/permission-handler.py 2>&1
```

---

## Security Considerations

1. **Handler Script Permissions**: Ensure `/tmp/chorus/hooks/permission-handler.py` is not world-writable
2. **Policy Injection**: Permission policies are stored as JSON strings - validate before saving
3. **Audit Logging**: All permission decisions logged to stderr for audit trails
4. **Deny-First Strategy**: Deny patterns checked before allow patterns
5. **Config Isolation**: Each task has separate config directory, preventing cross-task contamination

---

## Future Enhancements

- [ ] Per-task permission UI editor (JSON editor in task detail)
- [ ] Permission decision audit log in database
- [ ] Custom permission profiles (user-defined)
- [ ] Permission templates for common workflows
- [ ] Webhook integration for external authorization
- [ ] Permission request notification (desktop/email)

---

## Related Documentation

- `docs/PERMISSION_HANDLING.md` - Original permission modes research
- `PLAN.md` Phase 8.1 - Permission configuration implementation
- Claude Code Hooks: https://code.claude.com/docs/en/hooks.md
