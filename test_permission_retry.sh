#!/bin/bash
# Manual test script for permission retry workflow

set -e

BASE_URL="http://localhost:8000"

echo "=== Permission Retry Workflow Test ==="
echo ""

# 1. Create task
echo "1. Creating test task..."
TASK_ID=$(curl -s -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"title":"Permission Retry Test","description":"Test permission retry with restricted tools","initial_prompt":"List all Python files"}' \
  | jq -r '.id')
echo "   Task created: $TASK_ID"
echo ""

# 2. Start task (creates tmux session)
echo "2. Starting task (this creates tmux session)..."
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/start" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"List all Python files in this directory using ls"}' | jq -r '.message'
echo ""
sleep 3

# 3. Kill Claude and restart with restricted permissions
echo "3. Restarting Claude with restricted --allowedTools..."
SESSION_NAME="claude-task-$TASK_ID"

# Send Ctrl-C to stop Claude
tmux send-keys -t "$SESSION_NAME" C-c 2>/dev/null || true
sleep 0.5
tmux send-keys -t "$SESSION_NAME" C-c 2>/dev/null || true
sleep 1

# Restart Claude with restrictive permissions (only Read, Grep, Glob - no Bash!)
# Use a prompt that explicitly requires Bash tool
CLAUDE_CMD='claude -p "Use the Bash tool to execute the command: echo \"Hello from Chorus test\"" --allowedTools "Read,Grep,Glob" --output-format stream-json --verbose'
tmux send-keys -t "$SESSION_NAME" "$CLAUDE_CMD" Enter
echo "   Claude restarted with: --allowedTools \"Read,Grep,Glob\""
echo ""

# 4. Wait for permission denial
echo "4. Waiting for permission denial..."
for i in {1..30}; do
  sleep 1
  PENDING_PERM=$(curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq -r '.pending_permission // "null"')

  if [ "$PENDING_PERM" != "null" ]; then
    echo "   ✓ Permission denial detected!"
    curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '{status, claude_status, pending_permission}'
    echo ""
    break
  fi

  if [ $((i % 5)) -eq 0 ]; then
    echo "   Still waiting... (${i}s)"
  fi
done

if [ "$PENDING_PERM" = "null" ]; then
  echo "   ✗ Timeout - no permission denial detected"
  echo "   Checking tmux output..."
  tmux capture-pane -t "$SESSION_NAME" -p | tail -20
  exit 1
fi

# 5. Approve permission
echo "5. Approving permission for Bash..."
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/approve-permission-and-retry" \
  -H "Content-Type: application/json" \
  -d '{"tool":"Bash"}' | jq -r '.message'
echo ""

# 6. Verify task updated
echo "6. Verifying task state..."
curl -s "$BASE_URL/api/tasks/$TASK_ID" | jq '{status, allowed_tools, pending_permission}'
echo ""

# 7. Wait for Claude to complete
echo "7. Waiting for Claude to complete with new permissions..."
sleep 10

# 8. Check tmux output
echo "8. Checking final tmux output (last 30 lines)..."
tmux capture-pane -t "$SESSION_NAME" -p | tail -30
echo ""

# 9. Cleanup
echo "9. Cleaning up..."
curl -s -X POST "$BASE_URL/api/tasks/$TASK_ID/complete" \
  -H "Content-Type: application/json" \
  -d '{"result":"test completed"}' > /dev/null
echo "   Task completed"
echo ""

echo "=== Test Complete ==="
