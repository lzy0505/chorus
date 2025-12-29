# Chorus — Task-Centric Claude Session Orchestrator

## Overview

A lightweight orchestration system for managing multiple Claude Code tasks working on a single large project. Each task runs in its own tmux process, attached to a GitButler feature branch, with the ability to restart Claude sessions as needed.

### Core Concept

```
Task = tmux process + GitButler branch + ephemeral Claude sessions
```

- **Task** is the primary entity — represents a unit of work
- **tmux process** persists for the task's lifetime — provides isolation
- **Claude sessions** are ephemeral — can be restarted within the same tmux when they hang, lose focus, or need fresh context
- **GitButler branch** tracks all changes — commits automatically on task completion

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
│  │ • Branch info   │  │ • References    │  │ • Restart Claude button       ││
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
│  │    Task API     │  │  Document API   │  │      GitButler API          │ │
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
│  [task-auth]              [task-api]              [task-tests]           │
│  branch: feat/auth        branch: feat/api        branch: feat/tests     │
│  claude: running          claude: waiting         claude: stopped        │
│  restarts: 0              restarts: 2             restarts: 1            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Web Dashboard** | UI for managing tasks, viewing documents, handling permissions |
| **FastAPI Backend** | REST API + SSE; coordinates all components |
| **Task Monitor** | Background polling of tmux processes, detecting Claude status |
| **Document Manager** | Markdown file operations, outline parsing |
| **GitButler API** | Create branches, commit changes via GitButler MCP |
| **Desktop Notifier** | OS-native notifications for permission requests |
| **tmux** | Process isolation per task |

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
| `branch_name` | string? | GitButler branch name, nullable until started |
| `tmux_session` | string? | tmux session ID, nullable until started |
| `claude_status` | enum | `stopped`, `starting`, `idle`, `busy`, `waiting` |
| `claude_restarts` | int | Number of times Claude was restarted in this task |
| `last_output` | string | Last ~2000 chars of terminal output |
| `permission_prompt` | string? | Detected permission request text |
| `created_at` | datetime | Task creation time |
| `started_at` | datetime? | When tmux was spawned |
| `completed_at` | datetime? | When task was completed |
| `commit_message` | string? | Generated commit message on completion |
| `result` | string? | Completion notes or failure reason |

**Status Definitions:**
- `pending`: Task created, not yet started (no tmux, no branch)
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
│ branch_name         │◀─── GitButler feature branch
│ tmux_session        │◀─── tmux session ID
│ claude_status       │
│ claude_restarts     │
│ last_output         │
│ permission_prompt   │
│ created_at          │
│ started_at          │
│ completed_at        │
│ commit_message      │
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
   - Create GitButler feature branch: `gitbutler mcp create_branch --name {branch}`
   - Spawn tmux session: `tmux new-session -d -s task-{id} -c {project_root}`
   - Start Claude in tmux: `tmux send-keys "claude" Enter`
   - Send initial prompt with task description + document context

3. **Monitor Task** (`running` ↔ `waiting`)
   - Poll tmux output every 1 second
   - Detect Claude status (idle/busy/waiting)
   - On permission prompt: update status, send desktop notification
   - User can approve/deny from dashboard

4. **Restart Claude** (within `running`)
   - Kill current Claude process in tmux
   - Restart Claude: `tmux send-keys "claude" Enter`
   - Increment `claude_restarts` counter
   - Optionally re-send context prompt

5. **Complete Task** (`running` → `completed`)
   - User triggers completion from dashboard
   - Send prompt to Claude: "Generate a very short commit message for the changes made"
   - Capture commit message from Claude's response
   - Call GitButler: `gitbutler mcp update_branches` with commit message
   - Kill tmux session
   - Update task status to `completed`

6. **Fail Task** (`running` → `failed`)
   - User marks task as failed
   - Optionally discard GitButler branch
   - Kill tmux session
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
Start the task — creates branch, spawns tmux, launches Claude.

**Implementation:**
1. Create GitButler branch: `feat/{task_title_slug}`
2. Spawn tmux: `tmux new-session -d -s task-{id} -c {project_root}`
3. Start Claude: `tmux send-keys "claude" Enter`
4. Build prompt with task description + document references
5. Send prompt: `tmux send-keys "{prompt}" Enter`
6. Update task: `status = running`, `started_at = now()`, `tmux_session = task-{id}`

#### `POST /api/tasks/{task_id}/restart-claude`
Restart Claude session within the task's tmux.

**Request Body (optional):**
```json
{
  "resend_context": true
}
```

**Implementation:**
1. Send Ctrl+C to kill current Claude: `tmux send-keys -t {session} C-c`
2. Wait briefly
3. Start Claude: `tmux send-keys "claude" Enter`
4. Increment `claude_restarts`
5. If `resend_context`: rebuild and send prompt

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
Complete the task — generates commit message, commits via GitButler, kills tmux.

**Implementation:**
1. Send to Claude: "Generate a very short (1 line) commit message summarizing the changes made in this task."
2. Capture Claude's response (poll for idle status, extract message)
3. Call GitButler MCP: `update_branches` with commit message
4. Kill tmux session
5. Update task: `status = completed`, `completed_at = now()`, `commit_message = {msg}`

**Response:**
```json
{
  "id": 1,
  "status": "completed",
  "commit_message": "Add JWT authentication with login/logout endpoints",
  "completed_at": "2025-01-15T15:30:00Z"
}
```

#### `POST /api/tasks/{task_id}/fail`
Mark task as failed.

**Request Body:**
```json
{
  "reason": "Blocked by missing API spec",
  "discard_branch": false
}
```

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

### Task Monitor

**Purpose:** Background task polling tmux sessions for all running tasks.

**Implementation:**

```python
async def monitor_loop():
    while True:
        tasks = get_running_tasks()
        for task in tasks:
            output = capture_tmux_output(task.tmux_session)
            claude_status, permission = detect_status(output)

            if claude_status != task.claude_status:
                emit_event("claude_status", {...})

                if claude_status == "waiting":
                    send_desktop_notification(task.title, permission)
                    task.status = "waiting"
                    emit_event("task_status", {...})
                elif task.status == "waiting" and claude_status in ["idle", "busy"]:
                    task.status = "running"
                    emit_event("task_status", {...})

            task.claude_status = claude_status
            task.permission_prompt = permission
            task.last_output = output[-2000:]
            save(task)

        await asyncio.sleep(1)
```

### GitButler Integration

**Branch Creation:**
```bash
# Create feature branch for task
gitbutler mcp create_branch --name "feat/{task-slug}"
```

**Commit on Completion:**
```bash
# Sync all changes to branch with commit message
gitbutler mcp update_branches
```

Note: The exact GitButler MCP commands may vary based on the GitButler CLI/API.

### tmux Commands

```bash
# Create session for task
tmux new-session -d -s task-{id} -c {project_root}

# Start Claude
tmux send-keys -t task-{id} "claude" Enter

# Send prompt
tmux send-keys -t task-{id} "{prompt}" Enter

# Capture output
tmux capture-pane -t task-{id} -p -S -100

# Kill Claude (Ctrl+C)
tmux send-keys -t task-{id} C-c

# Kill session
tmux kill-session -t task-{id}
```

### Status Detection Patterns

```python
CLAUDE_IDLE = [
    r">\s*$",           # Claude's input prompt
    r"claude>\s*$",     # Alternative prompt
]

CLAUDE_WAITING = [
    r"\(y/n\)",         # Yes/no prompt
    r"Allow\?",         # Permission request
    r"Do you want to",  # Confirmation
    r"Proceed\?",       # Proceed prompt
]

def detect_status(output: str) -> tuple[str, str | None]:
    lines = output.strip().split("\n")[-20:]
    text = "\n".join(lines)

    for pattern in CLAUDE_WAITING:
        if re.search(pattern, text, re.IGNORECASE):
            # Extract the permission prompt
            return ("waiting", extract_prompt(lines))

    for pattern in CLAUDE_IDLE:
        if re.search(pattern, lines[-1] if lines else ""):
            return ("idle", None)

    return ("busy", None)
```

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
│  │  ● Implement auth        [RUNNING]  branch: feat/auth    P:10      ││
│  │    Claude: BUSY          restarts: 0                               ││
│  │    [Restart Claude] [Send Message] [Complete] [Fail]               ││
│  │                                                                     ││
│  │  ⚠ Add rate limiting     [WAITING]  branch: feat/rate   P:5       ││
│  │    Claude: WAITING       "Allow write to api.py?"                  ││
│  │    [Approve] [Deny] [Restart Claude]                               ││
│  │                                                                     ││
│  │  ○ Setup tests           [PENDING]                       P:0       ││
│  │    [Start Task]                                                    ││
│  │                                                                     ││
│  │  ✓ Initial setup         [COMPLETED]  commit: "Initial setup"     ││
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
   - Shows task status, Claude status, branch name, restart count
   - Action buttons contextual to status
   - Waiting tasks show permission prompt inline

2. **Task Actions:**
   - **Start Task**: Creates branch, spawns tmux, launches Claude
   - **Restart Claude**: Kills and restarts Claude in tmux
   - **Send Message**: Opens modal to send additional instructions
   - **Complete**: Triggers commit flow
   - **Fail**: Marks task failed with reason
   - **Approve/Deny**: Responds to permission prompt

3. **Document Viewer:**
   - Line selection → add reference to a task

---

## Implementation Phases

### Phase 1: Core Foundation
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions
- [x] Database setup
- [x] tmux service wrapper

### Phase 2: Task API + Monitor (Priority: tmux focus)
- [ ] Update models.py with new Task fields
- [ ] `services/detector.py` - Status detection patterns
- [ ] `services/gitbutler.py` - GitButler MCP integration
- [ ] `api/tasks.py` - Full task lifecycle endpoints
- [ ] `services/monitor.py` - Task polling loop
- [ ] `api/events.py` - SSE endpoint

### Phase 3: Document API
- [ ] `services/documents.py` - Document manager
- [ ] `api/documents.py` - Document endpoints
- [ ] Document reference endpoints

### Phase 4: Dashboard
- [ ] Task-centric dashboard layout
- [ ] htmx interactions for all actions
- [ ] SSE integration

### Phase 5: Polish
- [ ] Error handling
- [ ] Edge cases (Claude crash, tmux death)
- [ ] Desktop notifications
- [ ] Manual testing

---

## Configuration

### Environment Variables

```bash
PROJECT_ROOT=/path/to/your/project    # Required
EDITOR=nvim                           # Optional
PORT=8000                             # Optional
POLL_INTERVAL=1.0                     # Status polling interval
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
| **Task** | A unit of work with its own tmux process and GitButler branch |
| **tmux process** | Terminal session that persists for task lifetime |
| **Claude session** | Ephemeral Claude Code instance within tmux (can be restarted) |
| **GitButler branch** | Feature branch managed by GitButler for task changes |
| **Document** | A tracked markdown file providing context |
| **Reference** | A link from a task to specific lines in a document |
| **Permission Prompt** | When Claude asks for confirmation (y/n) |
