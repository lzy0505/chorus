# Claude Code JSON Event Stream Format

This document describes the JSON event format produced by Claude Code when running with `--output-format stream-json`.

## Overview

Claude Code outputs newline-delimited JSON events to represent the conversation flow, tool usage, and responses. Each event is a single JSON object on one line (though terminal wrapping may split long events across multiple lines).

## Event Structure

All events share a common structure:

```json
{
  "type": "event_type",
  "session_id": "optional-session-id",
  ...additional fields vary by type
}
```

## Event Types

### 1. `session_start`

Emitted when a Claude session begins (or resumes).

**Fields:**
- `type`: "session_start"
- `session_id`: String - Unique session identifier for `--resume`

**Example:**
```json
{
  "type": "session_start",
  "session_id": "abc123..."
}
```

**Usage:** Chorus extracts `session_id` to enable session resumption with `--resume`.

---

### 2. `user`

Represents user input to Claude.

**Fields:**
- `type`: "user"
- `message`: Object
  - `role`: "user"
  - `content`: String or Array of content blocks
    - For text: `[{"type": "text", "text": "..."}]`
    - Can include images and other content types

**Example:**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "Please update the README"
      }
    ]
  }
}
```

---

### 3. `tool_use`

Emitted when Claude decides to use a tool.

**Fields:**
- `type`: "tool_use"
- `id`: String - Unique tool use ID (for pairing with `tool_result`)
- `toolName`: String - Tool name (e.g., "Read", "Edit", "Write", "Bash")
- `toolInput`: Object - Tool-specific parameters
  - For file tools: `file_path`, `old_string`, `new_string`, `content`, etc.
  - For Bash: `command`, `description`, `timeout`, etc.
  - For search: `pattern`, `glob`, `path`, etc.

**Example - File Edit:**
```json
{
  "type": "tool_use",
  "id": "toolu_abc123",
  "toolName": "Edit",
  "toolInput": {
    "file_path": "/path/to/file.py",
    "old_string": "def old():\n    pass",
    "new_string": "def new():\n    return True"
  }
}
```

**Example - Bash Command:**
```json
{
  "type": "tool_use",
  "id": "toolu_def456",
  "toolName": "Bash",
  "toolInput": {
    "command": "git status",
    "description": "Check git status"
  }
}
```

**Usage:** Chorus monitors for file-editing tools (`Edit`, `Write`, `MultiEdit`) and calls GitButler pre-tool hooks before the tool executes.

---

### 4. `tool_result`

Emitted after a tool completes execution.

**Fields:**
- `type`: "tool_result"
- `toolUseId`: String - Matches the `id` from corresponding `tool_use` event
- `isError`: Boolean - Whether the tool execution failed
- `content`: String or Object - Tool output or error message

**Example - Success:**
```json
{
  "type": "tool_result",
  "toolUseId": "toolu_abc123",
  "isError": false,
  "content": "File updated successfully"
}
```

**Example - Error:**
```json
{
  "type": "tool_result",
  "toolUseId": "toolu_def456",
  "isError": true,
  "content": "Error: File not found"
}
```

**Usage:** Chorus calls GitButler post-tool hooks for successful file edits, triggering auto-commits.

---

### 5. `text`

Represents streaming text output from Claude (mid-response).

**Fields:**
- `type`: "text"
- `text`: String - Partial response text

**Example:**
```json
{
  "type": "text",
  "text": "I'll help you update the README file."
}
```

**Note:** Multiple `text` events may be emitted as Claude streams its response.

---

### 6. `assistant`

Represents a complete assistant message (contains all content blocks).

**Fields:**
- `type`: "assistant"
- `message`: Object
  - `role`: "assistant"
  - `content`: Array of content blocks
    - Text blocks: `{"type": "text", "text": "..."}`
    - Tool use blocks: `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}`
    - Thinking blocks: `{"type": "thinking", "thinking": "..."}`

**Example:**
```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "I'll update the README for you."
      },
      {
        "type": "tool_use",
        "id": "toolu_123",
        "name": "Edit",
        "input": {
          "file_path": "README.md",
          "old_string": "# Old Title",
          "new_string": "# New Title"
        }
      }
    ]
  }
}
```

**Usage:** Chorus extracts text content from `content` blocks to show Claude's responses in the UI.

---

### 7. `result`

Emitted when a request completes.

**Fields:**
- `type`: "result"
- `sessionId`: String (optional) - Session ID for resumption
- `result`: Object or String
  - When Object:
    - `stopReason`: String - Why completion stopped ("end_turn", "max_tokens", "stop_sequence", etc.)
    - `usage`: Object
      - `inputTokens`: Integer
      - `outputTokens`: Integer
  - When String: Simple result message

**Example:**
```json
{
  "type": "result",
  "sessionId": "abc123...",
  "result": {
    "stopReason": "end_turn",
    "usage": {
      "inputTokens": 1523,
      "outputTokens": 842
    }
  }
}
```

**Usage:** Chorus extracts `sessionId` for future `--resume` capability and displays token usage.

---

### 8. `permission_request`

Emitted when Claude asks for user confirmation (e.g., dangerous operations).

**Fields:**
- `type`: "permission_request"
- `prompt`: String - Permission prompt text
- `metadata`: Object (optional) - Additional context

**Example:**
```json
{
  "type": "permission_request",
  "prompt": "Allow Claude to execute 'rm -rf /tmp/build'?"
}
```

**Usage:** Chorus displays permission UI with Approve/Deny buttons and sends confirmation via tmux.

---

### 9. `error`

Emitted when an error occurs.

**Fields:**
- `type`: "error"
- `error`: Object
  - `type`: String - Error type
  - `message`: String - Error description

**Example:**
```json
{
  "type": "error",
  "error": {
    "type": "api_error",
    "message": "Rate limit exceeded"
  }
}
```

---

### 10. `system`

System-level events (debugging, status updates).

**Fields:**
- `type`: "system"
- Various fields depending on system event

**Note:** Structure varies; primarily for debugging.

---

## Event Flow Examples

### Typical Conversation Flow

```
session_start
  ↓
user (input)
  ↓
text (streaming response)
text (more response)
  ↓
assistant (complete message)
  ↓
result (completion)
```

### Tool Usage Flow

```
user (input: "Update README")
  ↓
tool_use (Edit tool)
  ↓
tool_result (success)
  ↓
text (Claude's response about the edit)
  ↓
assistant (complete message)
  ↓
result (completion)
```

### Permission Request Flow

```
user (input: "Delete all test files")
  ↓
permission_request ("Allow rm -rf tests/?")
  ↓
[User responds via UI]
  ↓
tool_use (Bash with rm command)
  ↓
tool_result (success/failure)
  ↓
result (completion)
```

---

## Implementation Notes

### Line Wrapping

Terminal output may wrap long JSON events across multiple lines. The `JsonEventParser` in `services/json_parser.py` handles this by:

1. Detecting lines starting with `{` as new events
2. Accumulating continuation lines
3. Parsing complete JSON objects

### Event Pairing

- `tool_use` and `tool_result` are paired via `id` / `toolUseId`
- Chorus maintains a buffer of recent `tool_use` events to match with `tool_result` for GitButler hook integration

### Session ID Extraction

The `session_id` can appear in:
- `session_start` event (most common)
- `result` event as `sessionId` (fallback)

Chorus prioritizes `session_start` but also checks `result` events.

---

## See Also

- `services/json_monitor.py` - Event processing logic
- `services/json_parser.py` - JSON parsing with line-wrap handling
- `services/gitbutler.py` - GitButler hook integration triggered by events
