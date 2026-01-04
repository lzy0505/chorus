#!/usr/bin/env python3
"""Manual test script for permission retry workflow.

This script tests the end-to-end permission retry workflow:
1. Create a task
2. Start Claude with restrictive --allowedTools
3. Give it a prompt requiring Bash
4. Detect permission denial
5. Approve permission
6. Verify Claude restarts with updated permissions
"""

import json
import subprocess
import time
from pathlib import Path
import requests

BASE_URL = "http://localhost:8000"

def main():
    print("=== Permission Retry Workflow Test ===\n")

    # 1. Create task
    print("1. Creating test task...")
    response = requests.post(
        f"{BASE_URL}/api/tasks",
        json={
            "title": "Permission Retry Test",
            "description": "Test permission retry with restricted tools",
            "initial_prompt": "List all Python files in this directory"
        }
    )
    task = response.json()
    task_id = task["id"]
    print(f"   Task created: {task_id}\n")

    # 2. Start task (creates tmux session)
    print("2. Starting task (this creates tmux session)...")
    response = requests.post(
        f"{BASE_URL}/api/tasks/{task_id}/start",
        json={"prompt": "List all Python files in this directory using ls"}
    )
    print(f"   {response.json()['message']}\n")
    time.sleep(2)  # Let tmux session start

    # 3. Kill Claude and restart with restricted permissions
    print("3. Restarting Claude with restricted --allowedTools...")
    session_name = f"claude-task-{task_id}"

    # Send Ctrl-C to stop Claude
    subprocess.run(["tmux", "send-keys", "-t", session_name, "C-c"], check=False)
    time.sleep(0.5)
    subprocess.run(["tmux", "send-keys", "-t", session_name, "C-c"], check=False)
    time.sleep(1)

    # Restart Claude with restrictive permissions (only Read, Grep, Glob - no Bash!)
    claude_cmd = f'claude -p "List all Python files in the current directory using ls command" --allowedTools "Read,Grep,Glob" --output-format stream-json'
    subprocess.run(["tmux", "send-keys", "-t", session_name, claude_cmd, "Enter"], check=True)
    print(f"   Claude restarted with: --allowedTools \"Read,Grep,Glob\"\n")

    # 4. Wait for Claude to hit permission denial
    print("4. Waiting for permission denial...")
    for i in range(30):  # Wait up to 30 seconds
        time.sleep(1)
        response = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
        task = response.json()

        if task.get("pending_permission"):
            print(f"   ✓ Permission denial detected!")
            print(f"   Status: {task['status']}")
            print(f"   Claude status: {task['claude_status']}")
            print(f"   Pending permission: {json.loads(task['pending_permission'])}\n")
            break

        if i % 5 == 0:
            print(f"   Still waiting... ({i}s)")
    else:
        print("   ✗ Timeout - no permission denial detected")
        print("   Checking tmux output...")
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True,
            text=True
        )
        print(result.stdout[-500:])
        return

    # 5. Approve permission
    print("5. Approving permission for Bash...")
    response = requests.post(
        f"{BASE_URL}/api/tasks/{task_id}/approve-permission-and-retry",
        json={"tool": "Bash"}
    )
    result = response.json()
    print(f"   {result['message']}\n")

    # 6. Verify task updated
    print("6. Verifying task state...")
    response = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
    task = response.json()
    print(f"   Status: {task['status']}")
    print(f"   Allowed tools: {task.get('allowed_tools', 'None')}")
    print(f"   Pending permission: {task.get('pending_permission', 'None')}\n")

    # 7. Wait a bit and check if Claude successfully used Bash
    print("7. Waiting for Claude to complete with new permissions...")
    time.sleep(10)

    # Check tmux output
    print("8. Checking final tmux output...")
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p"],
        capture_output=True,
        text=True
    )
    output = result.stdout

    # Look for successful ls execution
    if "ls" in output.lower() and ("python" in output.lower() or ".py" in output.lower()):
        print("   ✓ Claude appears to have successfully used Bash!\n")
    else:
        print("   ? Could not confirm successful Bash execution")
        print("   Last 500 chars of output:")
        print(output[-500:])
        print()

    # Cleanup
    print("9. Cleaning up...")
    requests.post(f"{BASE_URL}/api/tasks/{task_id}/complete", json={"result": "test completed"})
    print("   Task completed\n")

    print("=== Test Complete ===")


if __name__ == "__main__":
    main()
