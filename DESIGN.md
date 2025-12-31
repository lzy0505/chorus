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
| `id` | int (PK) | Auto-increment ID |
| `title` | string | Short task title |
| `description` | string | Detailed task description (markdown supported) |
| `priority` | int | Higher = more important, default 0 |
| `status` | enum | `pending`, `running`, `waiting`, `completed`, `failed` |
| `stack_id` | string? | GitButler stack CLI ID, nullable until started |
| `tmux_session` | string? | tmux session ID, nullable until started |
| `claude_session_id` | string? | Legacy field (deprecated, to be removed) |
| `json_session_id` | string? | Claude Code session ID (from JSON events), used for `--resume` |
| `claude_status` | enum | `stopped`, `starting`, `idle`, `busy`, `waiting` |
| `claude_restarts` | int | Number of times Claude was restarted in this task |
| `last_output` | string | Last ~2000 chars of terminal output |
| `permission_prompt` | string? | Detected permission request text |
| `created_at` | datetime | Task creation time |
| `started_at` | datetime? | When tmux was spawned |
| `completed_at` | datetime? | When task was completed |
| `stack_name` | string? | GitButler stack name for reference |
| `result` | string? | Completion notes or failure reason |

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
   - Create GitButler stack: `but branch new {stack-name}`
   - Spawn tmux session: `tmux new-session -d -s task-{id} -c {project_root}`
   - Start ttyd for web terminal: `ttyd -W -p {7681+id} tmux attach -t task-{id}`
   - Write task context to `/tmp/chorus/task-{id}/context.md`
   - Start Claude with context: `claude --append-system-prompt "$(cat /tmp/.../context.md)"`

3. **Monitor Task** (`running` ↔ `waiting`)
   - Poll tmux output every 1 second
   - Detect Claude status (idle/busy/waiting)
   - On permission prompt: update status, send desktop notification
   - User can approve/deny from dashboard

4. **Restart Claude** (within `running`)
   - Kill current Claude process in tmux
   - Restart Claude with context: `claude --append-system-prompt "$(cat /tmp/.../context.md)"`
   - Increment `claude_restarts` counter
   - Context is automatically re-injected from existing file

5. **Complete Task** (`running` → `completed`)
   - User triggers completion from dashboard
   - GitButler auto-commits via its native hooks (`but claude post-tool/stop`)
   - Alternatively, manual commit: `but commit -m "message" {stack}`
   - Stop ttyd (release port)
   - Kill tmux session
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

GitButler uses **virtual branches** called **stacks** that can run in parallel. Multiple tasks can have their own stacks simultaneously in the same workspace.

**CLI (`but`):**
```bash
# Create a new stack for a task
but branch new task-{id}-{slug}

# Mark stack for auto-assignment (all new changes go here)
but mark task-{id}-{slug}

# Remove mark (before marking another stack)
but unmark

# List all stacks and their status
but status -j

# Show commits in a stack
but branch show {stack} -j

# Manual commit to a specific stack (rarely needed - GitButler auto-commits)
but commit -m "message" {stack}

# Delete a stack (when task fails/cancelled)
but branch delete {stack} --force
```

**Per-Task Stack Assignment (Concurrent Tasks):**
Chorus manages commits centrally — no environment variables needed.

```
tmux-1 (task 1):                    tmux-2 (task 2):
Claude edits files                  Claude edits files
    ↓                                   ↓
PostToolUse hook → notify Chorus    PostToolUse hook → notify Chorus
    ↓                                   ↓
Chorus looks up task by session_id  Chorus looks up task by session_id
    ↓                                   ↓
but commit -c task-1-auth           but commit -c task-2-api
```

**How it works:**
1. Chorus tracks `task.stack_name` in the database
2. JSON Monitor parses `stream-json` events from Claude's output
3. On `tool_result` event for Edit/Write tools, Chorus commits
4. Chorus looks up the task by `session_id` and retrieves `stack_name`
5. Chorus runs `but commit -c {stack_name}` to commit to the correct stack

**Task Lifecycle:**
```
Task Start:
  1. but branch new task-{id}-{slug}    # Create stack
  2. Store stack_name in task record    # Chorus tracks it
  3. Start Claude in tmux               # Chorus routes commits

Task Complete:
  1. Kill tmux session

Task Fail:
  1. Optionally: but branch delete {stack} --force
  2. Kill tmux session
```

**Chorus + GitButler Architecture:**
```
Claude Code (in tmux with --output-format stream-json)
    ↓ Edit/Write tool
    ↓ JSON event: tool_result
JSON Monitor (polls tmux output)
    ↓ Parse JSON events
    ↓ Detect file edits
Chorus API
    ↓ Look up task by session_id → get stack_name
    ↓ Run: but commit -c {stack_name}
    ↓ Update task status
Dashboard (real-time via SSE)
```

Chorus provides centralized orchestration via JSON monitoring for:
- Task-to-session mapping via `json_session_id`
- Deterministic event detection from structured JSON
- Real-time status updates to dashboard
- Task lifecycle management (start/complete/fail)
- Session resumption with `--resume`

### tmux Commands

```bash
# Create session for task
tmux new-session -d -s task-{id} -c {project_root}

# Start Claude with task context and shared hooks config
tmux send-keys -t task-{id} 'CLAUDE_CONFIG_DIR="/tmp/chorus/hooks/.claude" claude --append-system-prompt "$(cat /tmp/chorus/task-{id}/context.md)"' Enter

# Capture output
tmux capture-pane -t task-{id} -p -S -100

# Kill Claude (Ctrl+C)
tmux send-keys -t task-{id} C-c

# Kill session
tmux kill-session -t task-{id}
```

### Web Terminal Access (ttyd)

**Purpose:** Provide interactive web-based terminal access to task tmux sessions.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Task Detail View                                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  <iframe src="http://localhost:7682">                                 │  │
│  │     ┌─────────────────────────────────────────────────────────────┐   │  │
│  │     │  ttyd (xterm.js)                                            │   │  │
│  │     │  └── WebSocket ──► tmux attach -t task-1                    │   │  │
│  │     │                         └── Claude Code session             │   │  │
│  │     └─────────────────────────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**How it works:**

1. When a task starts, ttyd is launched attached to the task's tmux session
2. Port is calculated as `base_port (7681) + task_id`
3. The dashboard embeds ttyd in an iframe for full terminal interaction
4. When task completes/fails, ttyd is stopped and port is released

**TtydService (`services/ttyd.py`):**

```python
class TtydService:
    def start(self, task_id: int, session_id: str) -> TtydInfo:
        """Start ttyd for a task's tmux session."""
        port = 7681 + task_id
        cmd = ["ttyd", "-W", "-p", str(port), "tmux", "attach", "-t", session_id]
        # Launches ttyd in background, returns connection info

    def stop(self, task_id: int) -> None:
        """Stop ttyd for a task (releases port)."""

    def get_url(self, task_id: int) -> str:
        """Get ttyd URL for a task (e.g., http://localhost:7682)."""
```

**Key options:**
- `-W`: Writable mode (allows keyboard input)
- `-p PORT`: Port to listen on

**Lifecycle:**

| Event | Action |
|-------|--------|
| Task Start | `ttyd -W -p {7681+id} tmux attach -t {session}` |
| Task Running | iframe shows terminal, user can interact |
| Task Complete/Fail | `kill` ttyd process, port released |

**Benefits over polling-based terminal output:**
- Full terminal interaction (keyboard input, scrollback)
- Real-time updates (no 5-second polling delay)
- Copy/paste support
- Resizable terminal

**Note:** ttyd is optional. If not installed, tasks still work but without web terminal access.

### Task Context Injection

**Purpose:** Provide task-specific context to Claude Code without polluting the project directory.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│  POST /api/tasks/{id}/start                                 │
│                                                             │
│  1. Write context to /tmp/chorus/task-{id}/context.md       │
│  2. Start Claude with --append-system-prompt flag           │
│  3. Context persists for entire Claude session              │
│  4. Cleaned up when task completes/fails                    │
└─────────────────────────────────────────────────────────────┘
```

**Why `/tmp/` instead of project directory?**
- Context files are task-scoped and ephemeral
- No pollution in working directory or git history
- Each task's context is isolated (`/tmp/chorus/task-{id}/`)
- Automatically cleaned up on task completion

**Context File Format:**

```markdown
# Current Task: Fix authentication timeout bug
Task ID: 42
GitButler Stack: `task-42-fix-authentication-timeout-bug`

## Description
Users are getting logged out after 5 minutes instead of 30 minutes.
The session timeout config seems to be ignored.

## Git Workflow
- All changes for this task should be committed to stack: `task-42-fix-authentication-timeout-bug`
- Use `but commit -c task-42-fix-authentication-timeout-bug` to commit changes
- Do NOT use `git commit` directly

## Instructions
Check the JWT expiry settings in auth.py first
```

**How `--append-system-prompt` works:**
- Adds content to Claude's system prompt at startup
- Context is visible to Claude throughout the entire session
- Survives all interactions within the session
- Re-injected automatically on `restart-claude`

**Implementation (`services/context.py`):**

```python
CONTEXT_BASE_DIR = Path("/tmp/chorus")

def write_task_context(task: Task, user_prompt: str = None) -> Path:
    """Write task context to /tmp/chorus/task-{id}/context.md"""
    context_dir = CONTEXT_BASE_DIR / f"task-{task.id}"
    context_dir.mkdir(parents=True, exist_ok=True)

    context_file = context_dir / "context.md"
    context_file.write_text(build_task_context(task, user_prompt))
    return context_file

def cleanup_task_context(task_id: int) -> None:
    """Remove context directory on task completion/failure"""
    shutil.rmtree(CONTEXT_BASE_DIR / f"task-{task_id}", ignore_errors=True)
```

**Lifecycle:**

| Event | Action |
|-------|--------|
| Task Start | Write context to `/tmp/chorus/task-{id}/context.md` |
| Claude Start | `claude --append-system-prompt "$(cat /tmp/.../context.md)"` |
| Claude Restart | Re-inject same context file |
| Task Complete/Fail | Delete `/tmp/chorus/task-{id}/` directory |

### JSON Event Parsing

Chorus uses Claude Code's `--output-format stream-json` flag to get structured event data for deterministic status detection.

**JSON Events Parsed:**

| Event Type | When It Fires | Actions |
|------------|---------------|---------|
| `session_start` | Claude launches | Store `json_session_id`, set `claude_status = "idle"` |
| `tool_use` | Claude calls a tool | Detect file edits (Edit, Write tools) |
| `tool_result` | Tool completes | Trigger GitButler commit if file was modified |
| `text` | Claude outputs text | Update task output stream |
| `result` | Session completes | Extract final `session_id` for resumption |
| `error` | Error occurs | Log error, update task status |

**Stream-JSON Format:**

Claude outputs newline-delimited JSON when launched with `--output-format stream-json`:

```json
{"type":"session_start","session_id":"abc123"}
{"type":"tool_use","tool":{"name":"Read","input":{"file_path":"README.md"}}}
{"type":"tool_result","tool":"Read","result":"...file contents..."}
{"type":"text","text":"I can see the README..."}
{"type":"result","session_id":"abc123","stop_reason":"end_turn"}
```

**Parsing Architecture:**

```python
# services/json_parser.py
class JsonEventParser:
    def parse_line(self, line: str) -> Optional[ClaudeJsonEvent]:
        """Parse a single line of JSON output"""
        try:
            data = json.loads(line)
            event_type = data.get("type")
            session_id = data.get("session_id")
            return ClaudeJsonEvent(event_type=event_type, data=data, session_id=session_id)
        except json.JSONDecodeError:
            return None

    def parse_output(self, output: str) -> List[ClaudeJsonEvent]:
        """Parse multiple lines of JSON output"""
        events = []
        for line in output.splitlines():
            if event := self.parse_line(line):
                events.append(event)
        return events

# services/tmux.py
def capture_json_events(task_id: int) -> str:
    """Capture JSON events from tmux pane"""
    session_id = f"task-{task_id}"
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_id, "-p"],
        capture_output=True,
        text=True
    )
    return result.stdout
```

**Session Resumption:**

The `json_session_id` extracted from events enables resuming Claude sessions:

```bash
# Initial session
claude -p "Start working on auth" --output-format stream-json

# Resume same session later
claude -p "Continue" --resume <json_session_id> --output-format stream-json
```

Chorus automatically uses `--resume` when sending follow-up messages to a task.

### Spawned Session Authentication

Spawned Claude sessions need authentication to work. Claude Code's OAuth subscription authentication doesn't automatically propagate to isolated config directories. This section documents the authentication design.

**The Problem:**

When `CLAUDE_CONFIG_DIR` is set to an isolated directory, Claude Code:
1. Reads config/settings from that directory ✓
2. But OAuth tokens from browser-based login don't transfer automatically ✗

Simply copying `~/.claude.json` (which contains `oauthAccount` metadata) is **not sufficient** — it lacks the actual OAuth access tokens.

**The Solution:**

Claude Code supports `CLAUDE_CODE_OAUTH_TOKEN` for headless/automated authentication. Users must:

1. **Generate a long-lived OAuth token** (one-time setup):
   ```bash
   claude setup-token
   ```
   This opens a browser for OAuth flow and outputs a token.

2. **Set the environment variable** before starting Chorus:
   ```bash
   export CLAUDE_CODE_OAUTH_TOKEN="<token-from-step-1>"
   ```

3. **Chorus passes the token** to spawned Claude sessions:
   ```python
   # services/tmux.py - start_claude()
   env_vars = [f'CLAUDE_CONFIG_DIR="{config_dir}"']
   oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
   if oauth_token:
       env_vars.append(f'CLAUDE_CODE_OAUTH_TOKEN="{oauth_token}"')
   ```

**Additional Requirements:**

The isolated config's `.claude.json` must have `hasCompletedOnboarding: true` to skip the interactive onboarding flow. Chorus ensures this by copying the user's `~/.claude.json` (which has this flag set after initial login).

See: [GitHub Issue #8938](https://github.com/anthropics/claude-code/issues/8938)

**Credential Refresh:**

Credentials are inherited from the user's global `~/.claude.json` when starting tasks. The `CLAUDE_CODE_OAUTH_TOKEN` environment variable ensures spawned sessions authenticate properly.

---

## Dashboard Implementation

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Chorus                                                    [+ New Task] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ Tasks ─────────────────────────────────────────────────────────────┐│
│  │                                                                     ││
│  │  ● Implement auth        [RUNNING]  stack: task-1-auth   P:10      ││
│  │    Claude: BUSY          restarts: 0                               ││
│  │    [Restart Claude] [Send Message] [Complete] [Fail]               ││
│  │                                                                     ││
│  │  ⚠ Add rate limiting     [WAITING]  stack: task-2-rate   P:5      ││
│  │    Claude: WAITING       "Allow write to api.py?"                  ││
│  │    [Approve] [Deny] [Restart Claude]                               ││
│  │                                                                     ││
│  │  ○ Setup tests           [PENDING]                       P:0       ││
│  │    [Start Task]                                                    ││
│  │                                                                     ││
│  │  ✓ Initial setup         [COMPLETED]  stack: task-0-setup         ││
│  │                                                                     ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                         │
│  ┌─ Documents ──────────────────────────────────────────────────────┐  │
│  │ 📌 CLAUDE.md                    instructions                      │  │
│  │ 📄 docs/architecture.md         context                           │  │
│  │                                                                   │  │
│  │ ┌─ Viewer: docs/architecture.md ───────────────────────────────┐ │  │
│  │ │ ## Outline              │ ## Content                         │ │  │
│  │ │ > Architecture          │  # Architecture                    │ │  │
│  │ │   > Components          │  ...                               │ │  │
│  │ │                         │                                    │ │  │
│  │ │                         │ [Add lines 3-15 to Task #1]        │ │  │
│  │ └─────────────────────────┴────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Interactions

1. **Task List:**
   - Auto-refreshes via SSE on status changes
   - Shows task status, Claude status, stack name, restart count
   - Action buttons contextual to status
   - Waiting tasks show permission prompt inline

2. **Task Actions:**
   - **Start Task**: Creates stack, spawns tmux, launches Claude
   - **Restart Claude**: Kills and restarts Claude in tmux
   - **Send Message**: Opens modal to send additional instructions
   - **Complete**: Finalizes task (GitButler auto-commits)
   - **Fail**: Marks task failed, optionally deletes stack
   - **Approve/Deny**: Responds to permission prompt

3. **Document Viewer:**
   - Line selection → add reference to a task

---

## Implementation Phases

### Phase 1: Core Foundation ✅
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions
- [x] Database setup
- [x] tmux service wrapper

### Phase 2: Task API + JSON Monitoring ✅
- [x] `services/tmux.py` - Task-centric tmux operations
- [x] `services/json_parser.py` - Parse stream-json output
- [x] `services/monitor.py` - JSON event monitoring
- [x] `services/gitbutler.py` - GitButler CLI integration
- [x] `api/tasks.py` - Full task lifecycle endpoints
- [x] `api/events.py` - SSE endpoint for real-time updates

### Phase 3: Dashboard ✅
- [x] Task-centric dashboard layout
- [x] htmx interactions for all actions
- [x] SSE integration
- [x] Dark theme styling

### Phase 4: Polish & Reliability ✅
- [x] Error handling
- [x] Edge cases (Claude crash, tmux death)
- [x] Comprehensive logging system
- [x] JSON monitoring migration

### Phase 5: Future Enhancements
- [ ] Document API (`services/documents.py`, `api/documents.py`)
- [ ] Desktop notifications
- [ ] Integration tests with tmux
- [ ] Web terminal UI improvements

---

## Configuration

### TOML Configuration

Chorus uses a TOML configuration file passed as the first argument:

```bash
uv run python main.py chorus.toml /absolute/path/to/project
```

Example `chorus.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8000

[database]
url = "sqlite:///orchestrator.db"

[tmux]
session_prefix = "claude"
poll_interval = 1.0

[editor]
command = "vim"

[documents]
patterns = [
    "*.md",
    "docs/**/*.md",
    ".claude/**/*.md",
]

[logging]
level = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
log_subprocess = true  # Log external tool invocations (tmux, GitButler CLI, ttyd)
log_api_requests = true  # Log API endpoint calls

[status_polling]
enabled = true
interval = 5.0           # Poll every 5 seconds to verify status
frozen_threshold = 300.0 # Warn if Claude busy > 5 minutes

[notifications]
enabled = true

[status.idle]
patterns = ['>\\s*$', 'claude>\\s*$']

[status.waiting]
patterns = ['\\(y/n\\)', 'Allow\\?', 'Continue\\?']
```

### Logging Configuration

Chorus provides comprehensive logging for debugging, particularly useful when troubleshooting external tool interactions:

**Log Levels** (`logging.level`):
- `DEBUG`: Detailed information for diagnosing problems, includes all subprocess commands with full output
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages for unexpected but handled situations
- `ERROR`: Error messages for failures
- `CRITICAL`: Critical failures

**Subprocess Logging** (`logging.log_subprocess`):
When enabled, logs all external tool invocations with:
- Complete command line
- Exit codes
- stdout/stderr output (truncated for readability)
- Execution timing

Tools logged:
- `tmux` commands (session management, input/output)
- `but` GitButler CLI commands (stack operations, commits)
- `ttyd` process management (web terminal)

**API Request Logging** (`logging.log_api_requests`):
When enabled, logs all HTTP requests with:
- HTTP method and path
- Response status codes
- Error details

**Debugging Example:**

To debug tmux or GitButler issues:
```toml
[logging]
level = "DEBUG"
log_subprocess = true
log_api_requests = false
```

This will show detailed command execution:
```
2025-12-30 10:15:23 - services.tmux - DEBUG - Executing: tmux new-session -d -s claude-task-1 -c /path/to/project
2025-12-30 10:15:23 - services.tmux - DEBUG - Command succeeded: tmux new-session -d -s claude-task-1 -c /path/to/project
2025-12-30 10:15:24 - services.gitbutler - INFO - Creating GitButler stack: task-1-feature
2025-12-30 10:15:24 - services.gitbutler - DEBUG - Executing: but branch new task-1-feature -j
2025-12-30 10:15:24 - services.gitbutler - DEBUG - Command succeeded: but branch new task-1-feature -j
```

### Environment Variables

**CLAUDE_CODE_OAUTH_TOKEN** — Required for spawned Claude sessions to authenticate without interactive login. Generate with `claude setup-token`. See [Spawned Session Authentication](#spawned-session-authentication) for details.

```bash
export CLAUDE_CODE_OAUTH_TOKEN=<token-from-setup-token>
```

---

## Quick Start

```bash
# Start the orchestrator
cd chorus
uv run python main.py

# Open dashboard
open http://localhost:8000

# Workflow:
# 1. Create a task with description
# 2. Add document references for context
# 3. Start task (creates branch, launches Claude)
# 4. Monitor progress, approve permissions
# 5. Restart Claude if it hangs
# 6. Complete task (commits via GitButler)
```

---

## Glossary

| Term | Definition |
|------|------------|
| **Task** | A unit of work with its own tmux process and GitButler stack |
| **tmux process** | Terminal session that persists for task lifetime |
| **Claude session** | Ephemeral Claude Code instance within tmux (can be restarted) |
| **GitButler stack** | Virtual branch managed by GitButler for task changes (multiple can run in parallel) |
| **Stack CLI ID** | Short identifier (e.g., `tm`, `zl`) used by `but` commands to reference a stack |
| **Document** | A tracked markdown file providing context |
| **Reference** | A link from a task to specific lines in a document |
| **Permission Prompt** | When Claude asks for confirmation (y/n) |
| **`but`** | GitButler CLI command (e.g., `but status`, `but commit`) |
