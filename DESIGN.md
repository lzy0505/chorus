# Chorus — Task-Centric Claude Session Orchestrator

## Overview

A lightweight orchestration system for managing multiple Claude Code tasks working on a single large project. Each task runs in its own tmux process, attached to a GitButler feature branch, with the ability to restart Claude sessions as needed.

### Core Concept

```
Task = tmux process + GitButler stack + ephemeral Claude sessions
```

- **Task** is the primary entity — represents a unit of work
- **tmux process** persists for the task's lifetime — provides isolation
- **Claude sessions** are ephemeral — can be restarted within the same tmux when they hang, lose focus, or need fresh context
- **GitButler stack** (virtual branch) tracks all changes — GitButler auto-commits via its native hooks

### Goals

1. **Task Management**: Create, prioritize, and manage tasks with contextual information
2. **Session Resilience**: Restart Claude sessions without losing task context
3. **Git Integration**: Each task = one GitButler branch, auto-commit on completion
4. **Real-time Monitoring**: Web dashboard with live status updates
5. **Document Management**: Reference markdown files as task context

### Non-Goals

- Multi-project support (targets single large project)
- Complex role-based permissions (single user system)
- Authentication (local use only)

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Web Dashboard                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────────────────────┐│
│  │     Tasks       │  │   Documents     │  │     Alerts / Actions          ││
│  │                 │  │                 │  │                               ││
│  │ • Status        │  │ • Tree view     │  │ • Permission prompts          ││
│  │ • Stack info    │  │ • References    │  │ • Restart Claude button       ││
│  │ • Restart Claude│  │ • Line select   │  │ • Complete task button        ││
│  │ • Complete task │  │                 │  │                               ││
│  └─────────────────┘  └─────────────────┘  └───────────────────────────────┘│
│                         htmx + SSE (live updates)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend                                   │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │    Task API     │  │  Document API   │  │    GitButler Service        │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        SSE Event Stream                               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                   │                        │
          ▼                   ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐
│   Task Monitor   │  │     SQLite       │  │     Document Manager         │
│  (async polling) │  │    Database      │  │    (filesystem ops)          │
└──────────────────┘  └──────────────────┘  └──────────────────────────────┘
          │                                            │
          ▼                                            ▼
┌──────────────────┐                        ┌──────────────────────────────┐
│  Desktop Notify  │                        │      Project Filesystem      │
└──────────────────┘                        │      (markdown files)        │
          │                                 └──────────────────────────────┘
          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          tmux Processes (one per task)                    │
│                                                                          │
│  [task-1]                 [task-2]                [task-3]               │
│  stack: task-1-auth       stack: task-2-api       stack: task-3-tests    │
│  claude: running          claude: waiting         claude: stopped        │
│  restarts: 0              restarts: 2             restarts: 1            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Web Dashboard** | UI for managing tasks, viewing documents, handling permissions |
| **FastAPI Backend** | REST API + SSE; coordinates all components |
| **JSON Monitor** | Parse JSON events from Claude (`--output-format stream-json`), detect status, trigger GitButler commits |
| **JSON Parser** | Parse `stream-json` format, extract events and session metadata |
| **Document Manager** | Markdown file operations, outline parsing |
| **GitButler Service** | Create/manage stacks via `but` CLI, monitor stack status |
| **Desktop Notifier** | OS-native notifications for permission requests |
| **tmux** | Process isolation per task, capture JSON output |
| **ttyd Service** | Web terminal access via iframe (optional) |

---

## Data Models

### Task

The primary entity — a unit of work with its own tmux process and GitButler branch.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Task ID = Claude session ID = GitButler session identifier |
| `title` | string | Short task title |
| `description` | string | Detailed task description (markdown supported) |
| `priority` | int | Higher = more important, default 0 |
| `status` | enum | `pending`, `running`, `waiting`, `completed`, `failed` |
| `stack_name` | string? | GitButler auto-created stack name (e.g., "zl-branch-15"), discovered after first edit |
| `stack_cli_id` | string? | GitButler stack CLI ID (e.g., "u0"), nullable until first file edit |
| `tmux_session` | string? | tmux session ID, nullable until started |
| `claude_status` | enum | `stopped`, `starting`, `idle`, `busy`, `waiting` |
| `claude_restarts` | int | Number of times Claude was restarted in this task |
| `last_output` | string | Last ~2000 chars of terminal output |
| `permission_prompt` | string? | Detected permission request text |
| `created_at` | datetime | Task creation time |
| `started_at` | datetime? | When tmux was spawned |
| `completed_at` | datetime? | When task was completed |
| `result` | string? | Completion notes or failure reason |

**Key Design Decision: UUID as Primary Key**

The task ID is a UUID that serves triple duty:
1. **Task identifier** in Chorus database
2. **Claude session_id** for `--resume` support
3. **GitButler session identifier** for hooks (ensures each task gets its own auto-created stack)

This eliminates the need for mapping between different identifiers and ensures perfect isolation between concurrent tasks.

**Status Definitions:**
- `pending`: Task created, not yet started (no tmux, no stack)
- `running`: tmux process active, Claude is working
- `waiting`: Claude is asking for permission (y/n prompt detected)
- `completed`: Task finished, changes committed via GitButler
- `failed`: Task failed or was cancelled

**Claude Status Definitions:**
- `stopped`: Claude not running in tmux (can be restarted)
- `starting`: Claude is initializing
- `idle`: Claude at `>` prompt, waiting for input
- `busy`: Claude is processing
- `waiting`: Claude asking for permission

### Document

A tracked markdown file in the project.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK) | Auto-increment ID |
| `path` | string (unique) | Relative path from project root |
| `category` | string | `instructions`, `plans`, `communication`, `context`, `general` |
| `description` | string? | Optional human description |
| `pinned` | bool | Show at top of document list |
| `last_modified` | datetime | File modification time |

### DocumentReference

A reference to specific lines in a document, linked to a task.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK) | Auto-increment ID |
| `document_id` | int (FK) | Referenced document |
| `task_id` | int (FK) | Associated task |
| `start_line` | int | Start line (1-indexed, inclusive) |
| `end_line` | int | End line (1-indexed, inclusive) |
| `note` | string? | Why this section is relevant |
| `created_at` | datetime | Reference creation time |

### Entity Relationship Diagram

```
┌─────────────────────┐
│        Task         │
├─────────────────────┤
│ id (PK)             │
│ title               │
│ description         │
│ priority            │
│ status              │
│ stack_id            │◀─── GitButler stack CLI ID
│ stack_name          │◀─── GitButler stack name
│ tmux_session        │◀─── tmux session ID
│ claude_status       │
│ claude_restarts     │
│ last_output         │
│ permission_prompt   │
│ created_at          │
│ started_at          │
│ completed_at        │
│ result              │
└─────────────────────┘
          │
          │ 1:many
          ▼
┌─────────────────────┐       ┌─────────────────────┐
│  DocumentReference  │       │      Document       │
├─────────────────────┤       ├─────────────────────┤
│ id (PK)             │       │ id (PK)             │
│ task_id (FK)────────│───────│ path                │
│ document_id (FK)────│──────▶│ category            │
│ start_line          │       │ pinned              │
│ end_line            │       │ last_modified       │
│ note                │       └─────────────────────┘
│ created_at          │
└─────────────────────┘
```

---

## Task Lifecycle

### State Machine

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    ▼                                          │
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌───────────┐    │
│ pending │───▶│ running │───▶│ waiting │───▶│ completed │    │
└─────────┘    └─────────┘    └─────────┘    └───────────┘    │
     │              │              │                          │
     │              │              │         ┌────────┐       │
     │              └──────────────┴────────▶│ failed │       │
     │                                       └────────┘       │
     │                                            │           │
     └────────────────────────────────────────────┴───────────┘
                         (restart task)
```

### Workflow

1. **Create Task** (`pending`)
   - User creates task with title, description, priority
   - Optionally adds document references for context

2. **Start Task** (`pending` → `running`)
   - Generate UUID for task (used as task ID, Claude session ID, and GitButler session identifier)
   - Create transcript file: `/tmp/chorus/task-{uuid}/transcript.json` with `{"type":"user","cwd":"{project_root}"}`
   - Spawn tmux session: `tmux new-session -d -s task-{uuid} -c {project_root}`
   - Start ttyd for web terminal: `ttyd -W -p {7681+port} tmux attach -t task-{uuid}`
   - Write task context to `/tmp/chorus/task-{uuid}/context.md`
   - Start Claude with context: `claude --append-system-prompt "$(cat /tmp/.../context.md)"`
   - Note: GitButler stack is NOT pre-created; it's auto-created by hooks after first file edit

3. **Monitor Task** (`running` ↔ `waiting`)
   - Poll tmux output every 1 second for JSON events
   - Parse events to detect Claude status (idle/busy/waiting)
   - On **tool_use** event for Edit/Write/MultiEdit:
     - Call `but claude pre-tool` with task UUID and file path
   - On **tool_result** event (success) for Edit/Write/MultiEdit:
     - Call `but claude post-tool` with task UUID and file path
     - If this is the first edit, discover and save the auto-created stack name/CLI ID
     - Commit to the stack: `but commit {stack-name}`
   - On permission prompt: update status, send desktop notification
   - User can approve/deny from dashboard

4. **Restart Claude** (within `running`)
   - Kill current Claude process in tmux
   - Restart Claude with context: `claude --append-system-prompt "$(cat /tmp/.../context.md)"`
   - Increment `claude_restarts` counter
   - Context is automatically re-injected from existing file

5. **Complete Task** (`running` → `completed`)
   - User triggers completion from dashboard
   - Call `but claude stop` with task UUID to finalize GitButler session
   - Final commit if needed: `but commit {stack-name}`
   - Stop ttyd (release port)
   - Kill tmux session
   - Auto-created stack (e.g., "zl-branch-15") remains in GitButler for review/merge
   - Cleanup context: delete `/tmp/chorus/task-{id}/`
   - Update task status to `completed`

6. **Fail Task** (`running` → `failed`)
   - User marks task as failed
   - Optionally discard GitButler stack: `but branch delete {stack}`
   - Stop ttyd (release port)
   - Kill tmux session
   - Cleanup context: delete `/tmp/chorus/task-{id}/`
   - Record failure reason

---

## API Specification

### Task Endpoints

#### `POST /api/tasks`
Create a new task.

**Request Body:**
```json
{
  "title": "Implement user authentication",
  "description": "Add login/logout endpoints using JWT...",
  "priority": 10
}
```

**Response:** `201 Created` with Task object.

#### `GET /api/tasks`
List tasks with optional filtering.

**Query Parameters:**
- `status`: Filter by status
- `sort`: `priority` (default), `created_at`, `status`

#### `GET /api/tasks/{task_id}`
Get task details including document references.

#### `PUT /api/tasks/{task_id}`
Update task fields (title, description, priority).

#### `POST /api/tasks/{task_id}/start`
Start the task — creates stack, spawns tmux, launches Claude with task context.

**Request Body (optional):**
```json
{
  "initial_prompt": "Focus on the OAuth flow first"
}
```

**Implementation:**
1. Generate stack name: `task-{id}-{slug}`
2. Create GitButler stack: `but branch new {stack_name}`
3. Spawn tmux: `tmux new-session -d -s task-{id} -c {project_root}`
4. Write task context to `/tmp/chorus/task-{id}/context.md` (includes task description, stack info, and `initial_prompt`)
5. Start Claude with context: `claude --append-system-prompt "$(cat /tmp/chorus/task-{id}/context.md)"`
6. Update task: `status = running`, `started_at = now()`, `tmux_session = task-{id}`, `stack_name = {stack_name}`

**Note:** The `initial_prompt` is included in the context file under "## Instructions", not sent as a separate message. This ensures Claude sees all context in its system prompt.

#### `POST /api/tasks/{task_id}/restart-claude`
Restart Claude session within the task's tmux, re-injecting task context.

**Implementation:**
1. Send Ctrl+C to kill current Claude: `tmux send-keys -t {session} C-c`
2. Wait briefly
3. Start Claude with existing context: `claude --append-system-prompt "$(cat /tmp/chorus/task-{id}/context.md)"`
4. Increment `claude_restarts`

**Note:** Context is automatically re-injected from the existing `/tmp/chorus/task-{id}/context.md` file. No need to specify `resend_context` — it's always included.

#### `POST /api/tasks/{task_id}/send`
Send text to the task's Claude session.

**Request Body:**
```json
{
  "text": "Please also add unit tests"
}
```

#### `POST /api/tasks/{task_id}/respond`
Respond to a permission prompt.

**Request Body:**
```json
{
  "confirm": true
}
```

#### `POST /api/tasks/{task_id}/complete`
Complete the task — verifies commits, kills tmux.

**Implementation:**
1. Optionally verify stack has commits: `but branch show {stack} -j`
2. Kill tmux session (CHORUS_TASK_STACK env var is automatically cleaned up)
3. Update task: `status = completed`, `completed_at = now()`

**Response:**
```json
{
  "id": 1,
  "status": "completed",
  "completed_at": "2025-01-15T15:30:00Z"
}
```

**Note:** All commits during the task were routed to the task's stack via the custom hook + CHORUS_TASK_STACK env var.

#### `POST /api/tasks/{task_id}/fail`
Mark task as failed — optionally deletes stack, kills tmux.

**Request Body:**
```json
{
  "reason": "Blocked by missing API spec",
  "discard_stack": false
}
```

**Implementation:**
1. If `discard_stack`: Delete stack: `but branch delete {stack} --force`
2. Kill tmux session
3. Update task: `status = failed`, `result = {reason}`

#### `DELETE /api/tasks/{task_id}`
Delete task (only allowed for `pending` or `failed` tasks).

---

### Document Endpoints

#### `GET /api/documents`
List tracked documents.

**Query Parameters:**
- `category`: Filter by category
- `discover`: If `true`, scan filesystem for new markdown files

#### `GET /api/documents/{doc_id}`
Get document with content and outline.

#### `GET /api/documents/{doc_id}/lines`
Get specific line range.

#### `POST /api/documents/{doc_id}/references`
Create a reference to specific lines for a task.

**Request Body:**
```json
{
  "task_id": 1,
  "start_line": 10,
  "end_line": 45,
  "note": "Authentication requirements"
}
```

#### `GET /api/tasks/{task_id}/references`
Get all document references for a task.

#### `DELETE /api/references/{ref_id}`
Delete a document reference.

---

### Event Stream

#### `GET /api/events`
Server-Sent Events stream for real-time updates.

**Event Types:**

```
event: task_status
data: {"task_id": 1, "old_status": "running", "new_status": "waiting", "permission_prompt": "Allow?"}

event: claude_status
data: {"task_id": 1, "claude_status": "idle", "restarts": 2}

event: task_completed
data: {"task_id": 1, "commit_message": "Add auth endpoints"}

event: document_change
data: {"document_id": 1, "path": "docs/spec.md"}
```

---

## Component Implementation Details

### Important: Two "Hooks" Systems

Chorus documentation references two different "hooks" systems that serve different purposes:

| System | Purpose | Status | Location |
|--------|---------|--------|----------|
| **Claude Code hooks** | Monitor Claude sessions via callbacks (SessionStart, ToolUse, etc.) | DEPRECATED - replaced by JSON monitoring | `services/hooks.py` (legacy) |
| **GitButler hooks** | CLI commands for stack isolation (`but claude pre-tool/post-tool/stop`) | Methods implemented, not yet integrated | `services/gitbutler.py` |

**Current Architecture:**
- Monitoring: JSON-based (reads `stream-json` output)
- GitButler: CLI hooks defined but not yet called by `json_monitor.py`

### JSON Monitor Service

**Purpose:** Parse JSON events from Claude Code's `stream-json` output to track task status and trigger GitButler commits.

**Architecture:**

```
Claude Code (--output-format stream-json) → tmux captures output → JSON Monitor polls tmux → Parse events → Update task → SSE to dashboard
```

**Key Components:**

```python
# services/json_parser.py
class ClaudeJsonEvent:
    """Dataclass for parsed JSON events"""
    event_type: str  # "session_start", "tool_use", "tool_result", "text", "result", "error"
    data: dict
    session_id: Optional[str]

class JsonEventParser:
    """Parse stream-json output from Claude"""
    def parse_line(line: str) -> Optional[ClaudeJsonEvent]
    def parse_output(output: str) -> List[ClaudeJsonEvent]

# services/monitor.py
class Monitor:
    """Monitor Claude sessions via JSON events"""
    async def _monitor_task(task_id: int):
        output = tmux.capture_json_events(task_id)
        events = json_parser.parse_output(output)
        for event in events:
            await _handle_event(task_id, event)

    async def _handle_event(task_id: int, event: ClaudeJsonEvent):
        if event.event_type == "session_start":
            task.json_session_id = event.session_id
            task.claude_status = "idle"
        elif event.event_type == "tool_result":
            # Trigger GitButler commit after file edits
            if is_file_edit_tool(event.data["tool_name"]):
                gitbutler.commit_to_stack(task.stack_name)
        elif event.event_type == "result":
            # Extract session_id for resumption
            task.json_session_id = event.session_id
```

**Key Features:**
- **Session resumption** — Extract `session_id` from JSON for `--resume`
- **Deterministic event detection** — Parse structured JSON events
- **Self-contained monitoring** — Direct tmux output parsing

### GitButler Integration

GitButler provides **CLI hooks** (`but claude pre-tool/post-tool/stop`) that automatically create and manage stacks (virtual branches) per session. Chorus leverages these hooks to achieve perfect task isolation.

**Note:** These are NOT Claude Code's SessionStart/ToolUse callbacks (which have been replaced by JSON monitoring). These are GitButler-specific CLI commands.

#### Task as Logical Session

**Key Concept:** A Chorus **Task** maps to a single GitButler **session**, even if multiple Claude Code sessions are spawned for that task.

```
Task (UUID: abc-123)
  = GitButler session_id: abc-123 (persistent)
  = Transcript: /tmp/chorus/task-abc-123/
  = Tmux session: chorus-task-abc-123
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
