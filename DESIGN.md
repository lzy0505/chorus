# Chorus — Task-Centric Claude Session Orchestrator

## Overview

A lightweight orchestration system for managing multiple Claude Code tasks working on a single large project. Each task runs in its own tmux process, attached to a GitButler feature branch, with the ability to restart Claude sessions as needed.

### Core Concept

```
Task = tmux process + GitButler stack + ephemeral Claude sessions
```

- **Task** is the primary entity — represents a unit of work
- **tmux process** persists for the task's lifetime — provides isolation
- **Claude sessions** are ephemeral — can be restarted within the same tmux
- **GitButler stack** (virtual branch) tracks all changes — GitButler auto-commits via native hooks

### Goals

1. **Task Management**: Create, prioritize, and manage tasks with contextual information
2. **Session Resilience**: Restart Claude sessions without losing task context
3. **Git Integration**: Each task = one GitButler stack, auto-commit via hooks
4. **Real-time Monitoring**: Web dashboard with live status updates via JSON events
5. **Document Management**: Reference markdown files as task context

---

## Architecture

### High-Level Flow

```
User creates task → Start task (spawn tmux + Claude) → JSON Monitor polls events →
→ Detect file edits → Call GitButler hooks → Auto-create/commit to stack →
→ Real-time UI updates via SSE → Task completion
```

### Key Components

| Component | Responsibility |
|-----------|----------------|
| **FastAPI Backend** | REST API + SSE; coordinates all components |
| **JSON Monitor** | Parse JSON events from Claude (`--output-format stream-json`), detect status, trigger GitButler hooks |
| **JSON Parser** | Parse `stream-json` format, extract events and session metadata |
| **GitButler Service** | Call `but claude` hooks for stack isolation, commit changes |
| **tmux Service** | Process isolation per task, capture JSON output |
| **Web Dashboard** | UI for managing tasks, viewing documents, handling permissions |

### JSON-Based Monitoring (Current Architecture)

```
┌─────────────────────────────────────────────────────────────┐
│ services/tmux.py                                             │
│ └─ start_claude() → `claude --output-format stream-json`    │
│ └─ capture_json_events() → Capture JSON from tmux           │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/json_monitor.py (JSON Monitor)                     │
│ └─ poll_json_events() → Parse stream-json from tmux         │
│ └─ handle_tool_use() → Detect file edits                    │
│ └─ handle_tool_result() → Trigger GitButler commit          │
│ └─ handle_result() → Extract session_id for resumption      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/gitbutler.py                                        │
│ └─ call_pre_tool_hook() → but claude pre-tool               │
│ └─ call_post_tool_hook() → but claude post-tool             │
│ └─ call_stop_hook() → but claude stop                       │
│ └─ commit_to_stack() → but commit -c {stack}                │
└─────────────────────────────────────────────────────────────┘
```

**Key Features:**
- **Deterministic event detection** — Parse structured JSON events from Claude
- **Session resumption** — Extract `session_id` from JSON for `--resume`
- **Real-time status updates** — Event-driven architecture
- **Permission handling** — Non-interactive permission management with `--allowedTools`
- **Multi-step task support** — Resume sessions with `-p --resume` for sequential work

**Documentation:** See `docs/JSON_EVENTS.md` for complete event format specification.

---

## Data Models

### Task

The primary entity — a unit of work with its own tmux process and GitButler stack.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Task ID = Claude session ID = GitButler session identifier |
| `title` | string | Short task title |
| `description` | string | Detailed task description (markdown) |
| `priority` | int | Higher = more important, default 0 |
| `status` | enum | `pending`, `running`, `waiting`, `completed`, `failed` |
| `stack_name` | string? | GitButler auto-created stack (e.g., "zl-branch-15"), discovered after first edit |
| `stack_cli_id` | string? | GitButler stack CLI ID (e.g., "u0"), nullable until first edit |
| `tmux_session` | string? | tmux session ID, nullable until started |
| `claude_status` | enum | `stopped`, `starting`, `idle`, `busy`, `waiting` |
| `claude_session_id` | string? | Claude session ID for `--resume` support |
| `claude_restarts` | int | Number of times Claude was restarted |
| `allowed_tools` | string | JSON array of allowed tool patterns for `--allowedTools` |
| `pending_permission` | string? | Detected permission request details |
| `continuation_count` | int | Number of times task was continued with new prompt |
| `prompt_history` | string | JSON array of all prompts sent to this task |
| `last_output` | string | Last ~2000 chars of terminal output |
| `created_at` | datetime | Task creation time |
| `started_at` | datetime? | When tmux was spawned |
| `completed_at` | datetime? | When task was completed |
| `result` | string? | Completion notes or failure reason |

**Key Design: UUID as Primary Key**

The task ID is a UUID that serves triple duty:
1. **Task identifier** in Chorus database
2. **Claude session_id** for `--resume` support
3. **GitButler session identifier** for hooks (ensures each task gets its own auto-created stack)

This eliminates the need for mapping between different identifiers and ensures perfect isolation between concurrent tasks.

### Document & DocumentReference

See `models.py` for complete definitions. Documents are markdown files tracked for task context; DocumentReferences link specific line ranges to tasks.

---

## Task Lifecycle

### State Flow

```
pending → start_task() → running ↔ waiting (permissions) → complete_task() → completed
   ↓                        ↓                                      ↓
   └────── fail_task() ────┴──────────────────────────────────────┴──→ failed
```

### Workflow

1. **Create Task** (`pending`)
   - User creates task with title, description, priority
   - Optionally adds document references for context

2. **Start Task** (`pending` → `running`)
   - Generate UUID for task (used as task ID, Claude session ID, and GitButler session identifier)
   - Create transcript file: `/tmp/chorus/task-{uuid}/transcript.json`
   - Spawn tmux session: `tmux new-session -d -s task-{uuid}`
   - Start Claude with JSON output: `claude --output-format stream-json -p "{prompt}"`
   - Note: GitButler stack is NOT pre-created; it's auto-created by hooks after first file edit

3. **Monitor Task** (`running` ↔ `waiting`)
   - Poll tmux output every 1 second for JSON events
   - Parse events to detect Claude status and file edits
   - On **tool_use** event for Edit/Write/MultiEdit:
     - Call `but claude pre-tool` with task UUID and file path
   - On **tool_result** event (success):
     - Call `but claude post-tool` with task UUID and file path
     - If this is the first edit, discover and save the auto-created stack name
     - Commit to the stack: `but commit -c {stack-name}`
   - On permission denial detection:
     - Parse JSON events for permission errors
     - Prompt user to approve
     - Retry with `--allowedTools` flag

4. **Continue Task** (within `running`)
   - When Claude stops (completes prompt), allow user to send new prompt
   - Use `--resume {claude_session_id}` to continue same session
   - Track continuation count and prompt history

5. **Complete Task** (`running` → `completed`)
   - User triggers completion from dashboard
   - Call `but claude stop` with task UUID to finalize GitButler session
   - Kill tmux session
   - Auto-created stack remains in GitButler for review/merge
   - Update task status to `completed`

6. **Fail Task** (`running` → `failed`)
   - User marks task as failed
   - Optionally discard GitButler stack
   - Kill tmux session
   - Record failure reason

**See `PLAN.md` for detailed implementation notes.**

---

## API Specification

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tasks` | POST | Create new task |
| `/api/tasks` | GET | List tasks with filtering |
| `/api/tasks/{id}` | GET | Get task details |
| `/api/tasks/{id}/start` | POST | Start task (spawn tmux + Claude) |
| `/api/tasks/{id}/continue` | POST | Continue task with new prompt (`--resume`) |
| `/api/tasks/{id}/approve-permission-and-retry` | POST | Approve permission and retry with `--allowedTools` |
| `/api/tasks/{id}/complete` | POST | Complete task (call stop hook, kill tmux) |
| `/api/tasks/{id}/fail` | POST | Fail task (optionally delete stack) |
| `/api/events` | GET | SSE stream for real-time updates |

**See `api/` directory for complete endpoint implementations.**

---

## Component Details

### GitButler Integration - "Task as Logical Session"

**Key Concept:** A Chorus **Task** maps to a single GitButler **session**, even if multiple Claude Code sessions are spawned for that task.

```
Task (UUID: abc-123)
  = GitButler session_id: abc-123 (persistent)
  = Transcript: /tmp/chorus/task-abc-123/
  ├─ Claude session 1 (initial, session_id: xyz-111)
  │   └─ Edits → hooks use task_id (abc-123)
  ├─ [Claude crashes/restarts]
  └─ Claude session 2 (resumed, session_id: xyz-222)
      └─ Edits → hooks STILL use task_id (abc-123)

Result: All edits assigned to the same GitButler stack!
```

**Two Different UUIDs:**
- **Task UUID** (`task.id`): Used as `session_id` in GitButler hooks. Persistent across Claude restarts.
- **Claude Session UUID**: Used for Claude Code's `--resume` flag. Changes on each restart.

**Hook Workflow:**
1. **Pre-tool hook** (`but claude pre-tool`): Called BEFORE file edit
2. **Post-tool hook** (`but claude post-tool`): Called AFTER file edit
   - GitButler auto-creates a stack for this session (e.g., "zl-branch-15")
   - Same task UUID always uses the same stack (even across Claude restarts!)
3. **Stop hook** (`but claude stop`): Called when **task completes** (not when Claude restarts)

**Hook JSON Format:** See `design.md` (legacy, full version) or `services/gitbutler.py` for details.

**Benefits:**
- ✅ **No marking needed** - No global state, perfect for concurrent tasks
- ✅ **Automatic isolation** - Each task UUID → unique session → unique stack
- ✅ **Clean 1:1 mapping** - Task ID = Session ID = Stack session identifier

### JSON Event Monitoring

Chorus uses Claude Code's `--output-format stream-json` flag to get structured event data for deterministic status detection.

**Event Types Parsed:**

| Event Type | When It Fires | Actions |
|------------|---------------|---------|
| `session_start` | Claude launches | Store `claude_session_id`, set status = "idle" |
| `tool_use` | Claude calls a tool | Detect file edits (Edit, Write, MultiEdit tools) |
| `tool_result` | Tool completes | Trigger GitButler hooks and commit if file was modified |
| `text` | Claude outputs text | Update task output stream |
| `result` | Session completes | Extract final `session_id` for resumption |
| `error` | Error occurs | Log error, update task status |

**See `docs/JSON_EVENTS.md` for complete specification of all 10 event types.**

### Permission Management

Without permission flags, Claude Code's `-p` mode blocks indefinitely on permission prompts, making it unusable in tmux.

**Current Approach: Detection + `--allowedTools`**

1. **Detection**: Parse JSON events for permission denial patterns
2. **Prompt User**: Show permission request in UI
3. **Retry**: User approves → add to `--allowedTools` → retry with `--resume`

**Pattern Support:**
- `Bash(git:*)` - Allow all git commands
- `Bash(git commit:*)` - Allow git commit only
- `Edit`, `Write` - Allow file editing tools
- etc.

**See `docs/PERMISSION_HANDLING.md` for detailed configuration strategies.**

### tmux Session Management

```bash
# Create session for task
tmux new-session -d -s task-{uuid} -c {project_root}

# Start Claude with JSON output
tmux send-keys -t task-{uuid} 'claude --output-format stream-json -p "{prompt}"' Enter

# Capture JSON output
tmux capture-pane -t task-{uuid} -p -S -2000

# Kill session
tmux kill-session -t task-{uuid}
```

**See `services/tmux.py` for complete implementation.**

---

## Configuration

Chorus uses a TOML configuration file:

```toml
[server]
host = "127.0.0.1"
port = 8000

[database]
url = "sqlite:///orchestrator.db"

[tmux]
session_prefix = "claude"
poll_interval = 1.0

[logging]
level = "INFO"  # DEBUG for troubleshooting
log_subprocess = true
log_api_requests = true

[monitoring]
use_json_mode = true  # Recommended (vs legacy hook mode)

[status.idle]
patterns = ['>\\s*$', 'claude>\\s*$']

[status.waiting]
patterns = ['\\(y/n\\)', 'Allow\\?', 'Continue\\?']
```

**See `README.md` for complete configuration reference.**

---

## Key Documentation

| File | Content |
|------|---------|
| `CLAUDE.md` | Development guide, GitButler workflow, project structure |
| `TODO.md` | Current tasks and upcoming work |
| `PLAN.md` | Implementation phases, current status |
| `README.md` | Quick start, features, configuration |
| `docs/JSON_EVENTS.md` | Claude Code JSON event format (10 event types) |
| `docs/TERMINATION_HANDLING.md` | Process termination, `-p` flag behavior |
| `docs/PERMISSION_HANDLING.md` | Permission configuration strategies |
| `docs/STATUS_TRACKING.md` | Granular status tracking design |

---

## Terminology

| Term | Definition |
|------|------------|
| **Task** | A unit of work with its own tmux process and GitButler stack |
| **tmux process** | Terminal session that persists for task lifetime |
| **Claude session** | Ephemeral Claude Code instance within tmux (can be restarted) |
| **GitButler stack** | Virtual branch managed by GitButler for task changes |
| **Stack CLI ID** | Short identifier (e.g., `u0`) used by `but` commands |
| **Claude Code hooks** | DEPRECATED - SessionStart/ToolUse callbacks, replaced by JSON monitoring |
| **GitButler hooks** | `but claude pre-tool/post-tool/stop` - for stack isolation |
| **JSON events** | Structured output from `--output-format stream-json` |
| **Session resumption** | Continue Claude session with `--resume {session_id}` |

---

## Important Notes

### Two "Hooks" Systems

Chorus documentation references two different "hooks" systems:

| System | Purpose | Status |
|--------|---------|--------|
| **Claude Code hooks** | Monitor Claude sessions via callbacks (SessionStart, ToolUse) | DEPRECATED - replaced by JSON monitoring |
| **GitButler hooks** | CLI commands for stack isolation (`but claude pre-tool/post-tool/stop`) | IN USE |

**Current Architecture:**
- Monitoring: JSON-based (reads `stream-json` output)
- GitButler: CLI hooks for session-isolated stacks

### Authentication for Spawned Sessions

Claude Code's OAuth subscription authentication doesn't automatically propagate to isolated sessions. Users must:

1. Generate long-lived OAuth token: `claude setup-token`
2. Set environment variable: `export CLAUDE_CODE_OAUTH_TOKEN="<token>"`

Chorus passes this token to spawned Claude sessions via environment variables.

**See README.md for setup instructions.**

---

**For detailed implementation history and architectural decisions, see `PLAN.md`.**
