# Claude Session Orchestrator — Project Specification

## Overview

A lightweight orchestration system for managing multiple Claude Code sessions working on a single large project. Combines session management, task coordination, and markdown document management with real-time monitoring via a web dashboard.

### Goals

1. **Session Management**: Spawn, monitor, and interact with multiple Claude Code instances via tmux
2. **Task Coordination**: Create, prioritize, and assign tasks to sessions with contextual information
3. **Document Management**: View, select, and reference markdown files that serve as project instructions, plans, and agent communication
4. **Real-time Monitoring**: Web dashboard with live status updates and permission request handling
5. **Desktop Notifications**: OS-level alerts when Claude needs attention

### Non-Goals

- Git worktree management (user will use GitButler)
- Multi-project support (targets single large project)
- Complex role-based permissions (single user system)
- Authentication (local use only)

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Web Dashboard                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐  │
│  │  Sessions   │  │    Tasks    │  │  Documents  │  │  Permission       │  │
│  │  Panel      │  │    Panel    │  │  Viewer     │  │  Alerts           │  │
│  │             │  │             │  │             │  │                   │  │
│  │ • Status    │  │ • Create    │  │ • Tree view │  │ • Real-time popup │  │
│  │ • Attach    │  │ • Assign    │  │ • Outline   │  │ • Approve/Deny    │  │
│  │ • Kill      │  │ • Priority  │  │ • Line sel  │  │                   │  │
│  └─────────────┘  └─────────────┘  │ • Edit btn  │  └───────────────────┘  │
│                                    └─────────────┘                          │
│                         htmx + SSE (live updates)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend                                   │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │   Session API   │  │    Task API     │  │      Document API           │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        SSE Event Stream                               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                   │                        │
          ▼                   ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐
│  Session Monitor │  │     SQLite       │  │    Document Manager          │
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
│                            tmux Sessions                                  │
│   [claude-task-1]        [claude-task-2]        [claude-task-3]          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Web Dashboard** | UI for viewing/managing sessions, tasks, documents; handling permission prompts |
| **FastAPI Backend** | REST API + SSE event stream; coordinates all components |
| **Session Monitor** | Background async task polling tmux sessions, detecting status changes |
| **Document Manager** | Filesystem operations for markdown files; outline parsing; editor integration |
| **Desktop Notifier** | OS-native notifications for permission requests |
| **SQLite Database** | Persistence for sessions, tasks, documents, references |
| **tmux** | Terminal multiplexing; session isolation |

---

## Data Models

### Session

Represents a tmux session running Claude Code.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (PK) | tmux session name, format: `claude-{name}` |
| `task_id` | int? (FK) | Currently assigned task, nullable |
| `status` | enum | `idle`, `busy`, `waiting`, `stopped` |
| `last_output` | string | Last ~2000 chars of terminal output for status detection |
| `permission_prompt` | string? | Detected permission request text, nullable |
| `created_at` | datetime | Session creation time |
| `updated_at` | datetime | Last status update time |

**Status Definitions:**
- `idle`: Claude is at the `>` prompt, waiting for user input
- `busy`: Claude is processing (no prompt visible)
- `waiting`: Claude is asking for permission (y/n prompt detected)
- `stopped`: Session terminated or not responding

### Task

A unit of work to be assigned to a session.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK) | Auto-increment ID |
| `title` | string | Short task title |
| `description` | string | Detailed task description (markdown supported) |
| `priority` | int | Higher = more important, default 0 |
| `status` | enum | `pending`, `assigned`, `in_progress`, `blocked`, `completed`, `failed` |
| `session_id` | string? (FK) | Assigned session, nullable |
| `created_at` | datetime | Task creation time |
| `started_at` | datetime? | When task was assigned |
| `completed_at` | datetime? | When task was marked complete |
| `result` | string? | Completion notes or failure reason |

**Status Definitions:**
- `pending`: Not yet assigned
- `assigned`: Assigned to session, prompt sent
- `in_progress`: Claude is actively working (session status = busy)
- `blocked`: Session is waiting for permission
- `completed`: Task finished successfully
- `failed`: Task failed or was cancelled

### Document

A tracked markdown file in the project.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK) | Auto-increment ID |
| `path` | string (unique) | Relative path from project root |
| `category` | string | `instructions`, `plans`, `communication`, `context`, `general` |
| `description` | string? | Optional human description |
| `pinned` | bool | Show at top of document list, default false |
| `last_modified` | datetime | File modification time |

### DocumentReference

A reference to specific lines in a document, linked to a task.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK) | Auto-increment ID |
| `document_id` | int (FK) | Referenced document |
| `task_id` | int? (FK) | Associated task, nullable |
| `start_line` | int | Start line (1-indexed, inclusive) |
| `end_line` | int | End line (1-indexed, inclusive) |
| `note` | string? | Why this section is relevant |
| `created_at` | datetime | Reference creation time |

### Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     Session     │       │      Task       │       │    Document     │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │◀──┐   │ id (PK)         │   ┌──▶│ id (PK)         │
│ task_id (FK)────│───┼──▶│ session_id (FK) │   │   │ path            │
│ status          │   │   │ title           │   │   │ category        │
│ last_output     │   │   │ description     │   │   │ pinned          │
│ permission_prompt│  │   │ priority        │   │   │ last_modified   │
│ created_at      │   │   │ status          │   │   └─────────────────┘
│ updated_at      │   │   │ created_at      │   │
└─────────────────┘   │   │ started_at      │   │
                      │   │ completed_at    │   │
                      │   │ result          │   │
                      │   └─────────────────┘   │
                      │           │             │
                      │           ▼             │
                      │   ┌─────────────────┐   │
                      │   │DocumentReference│   │
                      │   ├─────────────────┤   │
                      │   │ id (PK)         │   │
                      │   │ document_id (FK)│───┘
                      └───│ task_id (FK)    │
                          │ start_line      │
                          │ end_line        │
                          │ note            │
                          │ created_at      │
                          └─────────────────┘
```

---

## API Specification

### Session Endpoints

#### `POST /api/sessions`
Create a new tmux session with Claude Code.

**Request Body:**
```json
{
  "name": "feature-auth",
  "initial_prompt": "Optional prompt to send immediately"
}
```

**Response:** `201 Created`
```json
{
  "id": "claude-feature-auth",
  "task_id": null,
  "status": "idle",
  "created_at": "2025-01-15T10:00:00Z"
}
```

**Implementation:**
1. Generate session ID: `claude-{name}`
2. Run: `tmux new-session -d -s {session_id} -c {project_root} "claude"`
3. Create Session record in database
4. If `initial_prompt` provided, send via `tmux send-keys`

#### `GET /api/sessions`
List all sessions.

**Response:** `200 OK`
```json
[
  {
    "id": "claude-feature-auth",
    "task_id": 1,
    "status": "busy",
    "permission_prompt": null,
    "updated_at": "2025-01-15T10:05:00Z"
  }
]
```

#### `GET /api/sessions/{session_id}`
Get session details including recent output.

**Response:** `200 OK`
```json
{
  "id": "claude-feature-auth",
  "task_id": 1,
  "status": "waiting",
  "permission_prompt": "Allow write to src/auth.py? (y/n)",
  "last_output": "... last 2000 chars ...",
  "updated_at": "2025-01-15T10:05:00Z"
}
```

#### `POST /api/sessions/{session_id}/send`
Send text to the session.

**Request Body:**
```json
{
  "text": "Please also add unit tests"
}
```

**Implementation:**
1. Run: `tmux send-keys -t {session_id} "{text}" Enter`

#### `POST /api/sessions/{session_id}/respond`
Respond to a permission prompt.

**Request Body:**
```json
{
  "confirm": true
}
```

**Implementation:**
1. Verify session status is `waiting`
2. Run: `tmux send-keys -t {session_id} "y" Enter` (or "n")
3. Clear `permission_prompt` field

#### `POST /api/sessions/{session_id}/attach`
Get tmux attach command (for user to run in terminal).

**Response:** `200 OK`
```json
{
  "command": "tmux attach-session -t claude-feature-auth"
}
```

#### `DELETE /api/sessions/{session_id}`
Kill session and clean up.

**Implementation:**
1. Run: `tmux kill-session -t {session_id}`
2. If linked task, update task status to `failed` or leave as-is
3. Delete Session record

---

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

**Response:** `200 OK`
```json
{
  "id": 1,
  "title": "Implement user authentication",
  "description": "...",
  "priority": 10,
  "status": "assigned",
  "session_id": "claude-feature-auth",
  "references": [
    {
      "id": 1,
      "document_path": "docs/auth-spec.md",
      "start_line": 10,
      "end_line": 45,
      "note": "Authentication requirements"
    }
  ]
}
```

#### `PUT /api/tasks/{task_id}`
Update task fields.

#### `POST /api/tasks/{task_id}/assign`
Assign task to a session.

**Request Body:**
```json
{
  "session_id": "claude-feature-auth"
}
```

**Implementation:**
1. Fetch task and all its DocumentReferences
2. For each reference, read the line range from the file
3. Build prompt:
   ```
   ## Task: {title}
   
   {description}
   
   ## Context
   
   ### From {path} (lines {start}-{end}):
   ```{content}```
   
   ### From {path2} (lines {start}-{end}):
   ```{content}```
   ```
4. Update task: `status = assigned`, `session_id = {session_id}`, `started_at = now()`
5. Update session: `task_id = {task_id}`
6. Send prompt: `tmux send-keys -t {session_id} "{prompt}" Enter`

#### `POST /api/tasks/{task_id}/complete`
Mark task as completed.

**Request Body:**
```json
{
  "result": "Implemented auth with JWT, added tests"
}
```

#### `POST /api/tasks/{task_id}/fail`
Mark task as failed.

---

### Document Endpoints

#### `GET /api/documents`
List tracked documents.

**Query Parameters:**
- `category`: Filter by category
- `discover`: If `true`, scan filesystem for new markdown files

**Implementation for discover:**
1. Glob project root for patterns: `*.md`, `docs/**/*.md`, `.claude/**/*.md`, `plans/**/*.md`
2. For each file not in database, create Document record
3. Update `last_modified` for existing records if file changed

#### `GET /api/documents/{doc_id}`
Get document with content and outline.

**Response:** `200 OK`
```json
{
  "id": 1,
  "path": "docs/architecture.md",
  "category": "instructions",
  "content": "# Architecture\n\n## Overview\n...",
  "outline": [
    {"line": 1, "level": 1, "text": "Architecture"},
    {"line": 3, "level": 2, "text": "Overview"},
    {"line": 15, "level": 2, "text": "Components"}
  ],
  "line_count": 150
}
```

**Outline Implementation:**
1. Read file content
2. For each line, check if starts with `#`
3. Count `#` chars for level, extract text
4. Return list of `{line, level, text}`

#### `GET /api/documents/{doc_id}/lines`
Get specific line range.

**Query Parameters:**
- `start`: Start line (1-indexed), default 1
- `end`: End line (inclusive), default EOF

**Response:** `200 OK`
```json
{
  "path": "docs/architecture.md",
  "start": 10,
  "end": 25,
  "lines": [
    {"number": 10, "content": "## Components"},
    {"number": 11, "content": ""},
    {"number": 12, "content": "The system consists of..."}
  ]
}
```

#### `GET /api/documents/{doc_id}/section/{header_line}`
Get content of a markdown section.

**Implementation:**
1. Parse outline to find header at `header_line`
2. Get header level
3. Find next header at same or higher level (or EOF)
4. Return lines from `header_line` to `next_header - 1`

#### `POST /api/documents/{doc_id}/edit`
Open document in external editor.

**Query Parameters:**
- `line`: Line number to jump to

**Implementation:**
1. Get `$EDITOR` environment variable (default: `vim`)
2. For vim/nvim/nano: `{editor} +{line} {path}`
3. For VS Code: `code --goto {path}:{line}`
4. Run as subprocess (non-blocking)

#### `PUT /api/documents/{doc_id}`
Update document content (for in-dashboard editing if implemented).

#### `PATCH /api/documents/{doc_id}`
Update document metadata (category, pinned, description).

---

### Document Reference Endpoints

#### `POST /api/documents/{doc_id}/references`
Create a reference to specific lines.

**Request Body:**
```json
{
  "task_id": 1,
  "start_line": 10,
  "end_line": 45,
  "note": "Authentication requirements"
}
```

**Response:** `201 Created` with DocumentReference object.

#### `GET /api/tasks/{task_id}/references`
Get all document references for a task.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "document": {"id": 1, "path": "docs/auth-spec.md"},
    "start_line": 10,
    "end_line": 45,
    "content": "## Authentication\n\nUsers must...",
    "note": "Authentication requirements"
  }
]
```

#### `DELETE /api/references/{ref_id}`
Delete a document reference.

---

### Event Stream

#### `GET /api/events`
Server-Sent Events stream for real-time updates.

**Event Types:**

```
event: session_status
data: {"session_id": "claude-auth", "old_status": "busy", "new_status": "waiting", "permission_prompt": "Allow?"}

event: task_update
data: {"task_id": 1, "status": "in_progress"}

event: document_change
data: {"document_id": 1, "path": "docs/spec.md"}
```

**Implementation:**
1. Create async queue for events
2. Session Monitor pushes events to queue
3. SSE endpoint yields events from queue
4. Frontend uses `EventSource` to subscribe

---

## Component Implementation Details

### Session Monitor

**Purpose:** Background task that polls tmux sessions and detects status changes.

**Implementation:**

1. **Polling Loop** (runs every 1 second):
   ```
   for each session in database:
     output = capture_tmux_output(session.id, lines=100)
     new_status, permission_prompt = detect_status(output)
     
     if new_status != session.status:
       emit_event("session_status", {...})
       
       if new_status == "waiting":
         send_desktop_notification(session.id, permission_prompt)
       
       if session.task_id:
         update_task_status_from_session(session.task_id, new_status)
     
     session.status = new_status
     session.permission_prompt = permission_prompt
     session.last_output = output[-2000:]
     session.updated_at = now()
     save(session)
   ```

2. **Status Detection Patterns:**
   ```
   IDLE patterns (check last 5 lines):
   - r">\s*$"           # Claude's input prompt
   - r"claude>\s*$"     # Alternative prompt
   
   WAITING patterns (check last 20 lines):
   - r"\(y/n\)"         # Yes/no prompt
   - r"Allow\?"         # Permission request
   - r"Do you want to"  # Confirmation
   - r"Proceed\?"       # Proceed prompt
   - r"Press Enter"     # Continue prompt
   
   Detection order:
   1. Check WAITING patterns first (higher priority)
   2. Check IDLE patterns
   3. Default to BUSY
   ```

3. **tmux Commands:**
   ```bash
   # Capture output
   tmux capture-pane -t {session_id} -p -S -100
   
   # Send text
   tmux send-keys -t {session_id} "{text}" Enter
   
   # List sessions
   tmux list-sessions -F "#{session_name}"
   
   # Kill session
   tmux kill-session -t {session_id}
   ```

### Document Manager

**Purpose:** Filesystem operations for markdown files.

**Implementation:**

1. **File Discovery:**
   ```
   patterns = ["*.md", "docs/**/*.md", ".claude/**/*.md", "plans/**/*.md"]
   
   for pattern in patterns:
     if "**" in pattern:
       files = project_root.rglob(pattern.replace("**/", ""))
     else:
       files = project_root.glob(pattern)
   
   return unique sorted files
   ```

2. **Outline Parsing:**
   ```
   outline = []
   for line_num, line in enumerate(content.split("\n"), 1):
     if line.startswith("#"):
       level = count leading "#" chars
       text = line.lstrip("#").strip()
       outline.append({line: line_num, level: level, text: text})
   return outline
   ```

3. **Section Extraction:**
   ```
   Given header_line:
   1. Find header at that line, get its level
   2. Scan forward for next header with level <= current level
   3. Return lines from header_line to (next_header - 1) or EOF
   ```

4. **External Editor:**
   ```
   editor = os.environ.get("EDITOR", "vim")
   
   if editor in ["vim", "nvim"]:
     subprocess.Popen([editor, f"+{line}", path])
   elif editor == "code":
     subprocess.Popen([editor, "--goto", f"{path}:{line}"])
   else:
     subprocess.Popen([editor, path])
   ```

### Desktop Notifier

**Purpose:** OS-native notifications for permission requests.

**Implementation:**

```
system = platform.system()

if system == "Linux":
  subprocess.run(["notify-send", "--urgency=critical", title, body])
  
elif system == "Darwin":  # macOS
  script = f'display notification "{body}" with title "{title}"'
  subprocess.run(["osascript", "-e", script])
```

**Optional Enhancement:** Play sound for critical notifications.

---

## Dashboard Implementation

### Technology Stack

- **htmx**: Reactive updates without JavaScript framework
- **SSE**: Real-time updates via `EventSource`
- **Jinja2**: Server-side HTML templating
- **Minimal CSS**: Simple styling, no framework required

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Claude Orchestrator                                        [+ Session] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ Sessions ─────────────────────┐  ┌─ Tasks ────────────────────────┐│
│  │ ● claude-auth      [BUSY]      │  │ [ ] Implement auth    P:10    ││
│  │   Task: Implement auth         │  │     → claude-auth             ││
│  │                                │  │                               ││
│  │ ○ claude-api       [IDLE]      │  │ [ ] Add rate limiting P:5     ││
│  │   No task                      │  │     (pending)                 ││
│  │                                │  │                               ││
│  │ ⚠ claude-tests     [WAITING]   │  │ [x] Setup project    P:0      ││
│  │   Allow write to tests/?       │  │     (completed)               ││
│  │   [Approve] [Deny]             │  │                               ││
│  └────────────────────────────────┘  └───────────────────────────────┘│
│                                                                         │
│  ┌─ Documents ──────────────────────────────────────────────────────┐  │
│  │ 📌 CLAUDE.md                    instructions                      │  │
│  │ 📌 AGENTS.md                    instructions                      │  │
│  │ 📄 docs/architecture.md         context                           │  │
│  │ 📄 plans/auth-feature.md        plans                             │  │
│  │                                                                   │  │
│  │ ┌─ Viewer: docs/architecture.md ───────────────────────────────┐ │  │
│  │ │ ## Outline              │ ## Content (lines 1-50)            │ │  │
│  │ │                         │                                    │ │  │
│  │ │ > Architecture          │  1 │ # Architecture               │ │  │
│  │ │   > Overview            │  2 │                               │ │  │
│  │ │   > Components          │  3 │ ## Overview                   │ │  │
│  │ │     > Backend           │  4 │                               │ │  │
│  │ │     > Frontend          │  5 │ This system provides...       │ │  │
│  │ │   > Data Flow           │  6 │                               │ │  │
│  │ │                         │  7 │ ## Components                 │ │  │
│  │ │                         │    │ ...                           │ │  │
│  │ │                         │                                    │ │  │
│  │ │ [Edit in $EDITOR]       │ [Select lines 3-15 → Add to Task] │ │  │
│  │ └─────────────────────────┴────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Interactions

1. **Session Panel:**
   - Auto-refreshes via SSE on `session_status` events
   - Click session to view details
   - Waiting sessions show inline Approve/Deny buttons
   - `+ Session` button opens create form

2. **Task Panel:**
   - Drag-and-drop priority ordering (optional enhancement)
   - Click task to view/edit details
   - Assign button triggers session selection modal
   - Status badges with color coding

3. **Document Viewer:**
   - Outline panel: click header to jump to section
   - Content panel: line numbers, syntax highlighting (optional)
   - Line selection: click-drag to select range, button to create reference
   - Edit button: opens in `$EDITOR` at current line

### htmx Patterns

```html
<!-- Auto-refresh sessions on SSE event -->
<div id="sessions" 
     hx-get="/api/sessions" 
     hx-trigger="load, sse:session_status">
</div>

<!-- Approve permission -->
<button hx-post="/api/sessions/claude-tests/respond"
        hx-vals='{"confirm": true}'
        hx-swap="none">
  Approve
</button>

<!-- Load document content -->
<div hx-get="/api/documents/1/lines?start=1&end=50"
     hx-trigger="revealed">
</div>

<!-- Create reference from selection -->
<button hx-post="/api/documents/1/references"
        hx-vals='{"task_id": 1, "start_line": 3, "end_line": 15}'
        hx-target="#task-references">
  Add to Task
</button>
```

### SSE Integration

```javascript
const evtSource = new EventSource("/api/events");

evtSource.addEventListener("session_status", (e) => {
  const data = JSON.parse(e.data);
  htmx.trigger("#sessions", "sse:session_status");
  
  if (data.new_status === "waiting") {
    showPermissionAlert(data);
  }
});

evtSource.addEventListener("task_update", (e) => {
  htmx.trigger("#tasks", "sse:task_update");
});
```

---

## File Structure

```
claude-orchestrator/
├── main.py                 # Entry point: starts server + monitor
├── config.py               # Configuration (project root, patterns, etc.)
├── database.py             # SQLite setup, get_db dependency
├── models.py               # SQLModel definitions
│
├── api/
│   ├── __init__.py
│   ├── sessions.py         # Session endpoints
│   ├── tasks.py            # Task endpoints
│   ├── documents.py        # Document endpoints
│   └── events.py           # SSE stream endpoint
│
├── services/
│   ├── __init__.py
│   ├── tmux.py             # Tmux command wrapper
│   ├── monitor.py          # Session monitoring loop
│   ├── detector.py         # Status detection patterns
│   ├── documents.py        # Document manager
│   └── notifier.py         # Desktop notifications
│
├── templates/
│   ├── base.html           # Base layout
│   ├── dashboard.html      # Main dashboard
│   ├── partials/
│   │   ├── sessions.html   # Sessions panel
│   │   ├── tasks.html      # Tasks panel
│   │   ├── documents.html  # Documents panel
│   │   └── viewer.html     # Document viewer
│
├── static/
│   └── style.css           # Minimal styling
│
├── requirements.txt
├── README.md
└── CLAUDE.md               # This spec file, also serves as project instructions
```

---

## Implementation Phases

### Phase 1: Core Foundation (Day 1 Morning)

**Goal:** Basic project structure, database, tmux wrapper.

1. Create project structure
2. Implement `config.py`:
   - `PROJECT_ROOT`: Path to the project being managed
   - `SESSION_PREFIX`: Default "claude"
   - `POLL_INTERVAL`: Default 1.0 seconds
   - `DOCUMENT_PATTERNS`: List of glob patterns

3. Implement `models.py`:
   - All SQLModel classes as specified
   - Enums for statuses

4. Implement `database.py`:
   - SQLite connection
   - Create tables on startup
   - `get_db` dependency for FastAPI

5. Implement `services/tmux.py`:
   - `create_session(name, initial_prompt)`
   - `kill_session(session_id)`
   - `list_sessions()`
   - `capture_output(session_id, lines)`
   - `send_keys(session_id, text)`
   - `send_confirmation(session_id, confirm)`

**Validation:** Can create/list/kill tmux sessions from Python.

### Phase 2: Session API + Monitor (Day 1 Afternoon)

**Goal:** Working session management with status detection.

1. Implement `services/detector.py`:
   - `detect_status(output) -> (status, permission_prompt)`
   - Pattern matching as specified

2. Implement `services/notifier.py`:
   - `notify(title, body, urgency)`
   - Platform detection

3. Implement `api/sessions.py`:
   - All session endpoints
   - Basic CRUD operations

4. Implement `services/monitor.py`:
   - `SessionMonitor` class
   - Async polling loop
   - Status change detection
   - Event emission (to queue)

5. Implement `api/events.py`:
   - SSE endpoint
   - Async event queue

6. Implement `main.py`:
   - FastAPI app setup
   - Start monitor as background task
   - Mount API routers

**Validation:** Can create sessions, monitor detects status changes, SSE events flow.

### Phase 3: Task API (Day 1 Evening)

**Goal:** Task management with session assignment.

1. Implement `api/tasks.py`:
   - CRUD endpoints
   - Assignment logic
   - Prompt building with context

2. Update `services/monitor.py`:
   - Sync task status with session status

**Validation:** Can create tasks, assign to sessions, prompt is sent.

### Phase 4: Document API (Day 2 Morning)

**Goal:** Document management and references.

1. Implement `services/documents.py`:
   - `DocumentManager` class
   - File discovery
   - Read/write operations
   - Outline parsing
   - Section extraction
   - External editor launching

2. Implement `api/documents.py`:
   - All document endpoints
   - Reference endpoints

3. Update task assignment:
   - Include document references in prompt

**Validation:** Can list documents, read lines, create references, assign tasks with context.

### Phase 5: Dashboard (Day 2 Afternoon)

**Goal:** Working web UI.

1. Create `templates/base.html`:
   - Basic HTML structure
   - htmx and SSE setup

2. Create `templates/dashboard.html`:
   - Three-panel layout

3. Create partials:
   - `sessions.html`: Session list with status indicators
   - `tasks.html`: Task list with assignment
   - `documents.html`: Document tree and viewer

4. Implement `static/style.css`:
   - Minimal, functional styling

5. Add HTML rendering to `main.py`:
   - Jinja2 templates
   - Static files

**Validation:** Dashboard shows sessions/tasks/documents, updates in real-time.

### Phase 6: Polish (Day 2 Evening)

**Goal:** Error handling, edge cases, documentation.

1. Error handling:
   - tmux session not found
   - File not found
   - Invalid line ranges
   - Database errors

2. Edge cases:
   - Session dies unexpectedly
   - File deleted while tracked
   - Empty document references

3. Documentation:
   - README with setup instructions
   - API documentation (FastAPI auto-generates)

4. Testing:
   - Manual testing of all flows
   - Fix issues discovered

**Validation:** System handles errors gracefully, documentation complete.

---

## Configuration

### Environment Variables

```bash
# Required
PROJECT_ROOT=/path/to/your/project

# Optional
EDITOR=nvim                    # External editor (default: vim)
SESSION_PREFIX=claude          # tmux session prefix
POLL_INTERVAL=1.0              # Status polling interval in seconds
DATABASE_URL=sqlite:///orchestrator.db
PORT=8000
HOST=127.0.0.1
```

### Document Patterns

Default patterns for markdown discovery:

```python
DOCUMENT_PATTERNS = [
    "*.md",
    "docs/**/*.md",
    ".claude/**/*.md",
    "plans/**/*.md",
    "specs/**/*.md",
]
```

### Status Detection Patterns

Configurable in `config.py`:

```python
STATUS_PATTERNS = {
    "idle": [
        r">\s*$",
        r"claude>\s*$",
    ],
    "waiting": [
        r"\(y/n\)",
        r"Allow\?",
        r"Do you want to",
        r"Proceed\?",
        r"Press Enter",
        r"Continue\?",
    ],
}
```

---

## Dependencies

### requirements.txt

```
fastapi>=0.110
uvicorn[standard]>=0.27
sqlmodel>=0.0.16
jinja2>=3.1
python-multipart>=0.0.9
aiosqlite>=0.20
```

### System Dependencies

- **tmux**: Must be installed and in PATH
- **Python 3.11+**: For modern async features
- **notify-send** (Linux) or **osascript** (macOS): For desktop notifications

---

## Testing Strategy

### Manual Testing Checklist

**Sessions:**
- [ ] Create new session
- [ ] Session appears in dashboard
- [ ] Status shows as IDLE initially
- [ ] Send prompt, status changes to BUSY
- [ ] Claude finishes, status returns to IDLE
- [ ] Trigger permission prompt, status shows WAITING
- [ ] Approve/deny from dashboard works
- [ ] Desktop notification appears for WAITING
- [ ] Kill session, removed from dashboard

**Tasks:**
- [ ] Create new task
- [ ] Set priority, appears in correct order
- [ ] Assign to session
- [ ] Prompt sent to Claude (visible in tmux)
- [ ] Task status syncs with session status
- [ ] Mark task complete
- [ ] Mark task failed

**Documents:**
- [ ] Documents discovered on startup
- [ ] Document list shows in dashboard
- [ ] Click document, content loads
- [ ] Outline navigation works
- [ ] Line range selection works
- [ ] Create reference to task
- [ ] Reference content included in assignment prompt
- [ ] Edit button opens $EDITOR
- [ ] Pinned documents appear first

**Real-time:**
- [ ] Dashboard updates without refresh
- [ ] Multiple browser tabs stay in sync
- [ ] SSE reconnects on disconnect

---

## Future Enhancements (Out of Scope for MVP)

1. **Task Dependencies**: Task A blocks Task B
2. **Auto-assignment**: When session becomes idle, auto-assign next pending task
3. **Session Logs**: Store full conversation history
4. **GitButler Integration**: API to switch virtual branches per session
5. **Prompt Templates**: Reusable templates with variables
6. **Metrics Dashboard**: Time tracking, completion rates
7. **Multi-user**: Authentication, user-specific views
8. **Keyboard Shortcuts**: Vim-style navigation in dashboard
9. **Mobile Responsive**: Dashboard works on phone
10. **Webhook Integration**: Notify external services on events

---

## Glossary

| Term | Definition |
|------|------------|
| **Session** | A tmux session running Claude Code |
| **Task** | A unit of work assigned to a session |
| **Document** | A tracked markdown file in the project |
| **Reference** | A link from a task to specific lines in a document |
| **Permission Prompt** | When Claude asks for confirmation (y/n) |
| **SSE** | Server-Sent Events, for real-time updates |
| **htmx** | Library for reactive HTML without JavaScript framework |

---

## Quick Start Commands

After implementing, the workflow is:

```bash
# Start the orchestrator
cd claude-orchestrator
python main.py

# Open dashboard
open http://localhost:8000

# In dashboard:
# 1. Create a session
# 2. Create a task
# 3. Browse documents, select relevant lines
# 4. Create references linking lines to task
# 5. Assign task to session
# 6. Watch Claude work, approve permissions as needed
# 7. Mark task complete when done
```

---

*This specification is intended to be consumed by Claude Code for implementation. Start with Phase 1 and proceed sequentially. Each phase should be validated before moving to the next.*
