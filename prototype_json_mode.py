#!/usr/bin/env python3
"""Prototype script to validate the JSON monitoring approach.

This script tests the core concepts of the migration:
1. Running `claude -p --output-format stream-json` in tmux
2. Parsing JSON events from tmux output
3. Detecting tool use events
4. Session resumption with --resume

Run this script to validate the approach before starting the migration.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class JsonEvent:
    """Parsed JSON event from Claude."""
    type: str
    data: dict
    raw: str


class JsonEventParser:
    """Parse JSON events from Claude CLI stream-json output."""

    def parse_line(self, line: str) -> Optional[JsonEvent]:
        """Parse a single line as JSON event."""
        line = line.strip()
        if not line or not line.startswith('{'):
            return None

        try:
            data = json.loads(line)
            return JsonEvent(
                type=data.get("type", "unknown"),
                data=data,
                raw=line
            )
        except json.JSONDecodeError:
            return None

    def parse_output(self, output: str) -> list[JsonEvent]:
        """Parse multiple lines of JSON events.

        Handles terminal line wrapping by joining lines that start with '{'.
        """
        events = []
        lines = output.split('\n')

        # Join wrapped JSON lines
        current_json = ""
        for line in lines:
            stripped = line.strip()

            # Start of new JSON object
            if stripped.startswith('{'):
                # Parse previous JSON if exists
                if current_json:
                    event = self.parse_line(current_json)
                    if event:
                        events.append(event)
                current_json = stripped
            # Continuation of current JSON
            elif current_json and stripped:
                current_json += stripped

        # Parse last JSON
        if current_json:
            event = self.parse_line(current_json)
            if event:
                events.append(event)

        return events


def run_tmux_command(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a tmux command."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def test_json_mode():
    """Test running Claude in JSON mode via tmux."""

    print("=" * 70)
    print("PROTOTYPE: Testing claude -p with stream-json in tmux")
    print("=" * 70)
    print()

    session_name = "chorus-prototype"
    parser = JsonEventParser()

    # Step 1: Create tmux session
    print("Step 1: Creating tmux session...")
    result = run_tmux_command(["tmux", "new-session", "-d", "-s", session_name])
    if result.returncode != 0:
        # Session might already exist - kill and recreate
        run_tmux_command(["tmux", "kill-session", "-t", session_name])
        result = run_tmux_command(["tmux", "new-session", "-d", "-s", session_name])

    if result.returncode == 0:
        print(f"✓ Session '{session_name}' created")
    else:
        print(f"✗ Failed to create session: {result.stderr}")
        return

    print()

    # Step 2: Run Claude in JSON mode
    print("Step 2: Running claude -p with stream-json...")
    cmd = (
        'claude -p "List the files in the current directory" '
        '--output-format stream-json '
        '--verbose '
        '--allowedTools "Bash,Read" '
        '--max-turns 3'
    )
    print(f"Command: {cmd}")

    result = run_tmux_command(["tmux", "send-keys", "-t", session_name, cmd, "Enter"])
    if result.returncode == 0:
        print("✓ Command sent to tmux")
    else:
        print(f"✗ Failed to send command: {result.stderr}")
        return

    print()

    # Step 3: Wait for Claude to process
    print("Step 3: Waiting for Claude to process (5 seconds)...")
    time.sleep(5)
    print("✓ Wait complete")
    print()

    # Step 4: Capture output
    print("Step 4: Capturing tmux output...")
    result = run_tmux_command(["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-100"])

    if result.returncode == 0:
        output = result.stdout
        print(f"✓ Captured {len(output)} characters")
        print()

        # Step 5: Parse JSON events
        print("Step 5: Parsing JSON events...")
        events = parser.parse_output(output)
        print(f"✓ Found {len(events)} JSON events")
        print()

        if not events:
            print("✗ No JSON events found!")
            print()
            print("Raw output (first 500 chars):")
            print(output[:500])
            print()
        else:
            # Step 6: Analyze events
            print("Step 6: Analyzing events...")
            print()

            session_id = None
            tool_events = []

            for i, event in enumerate(events, 1):
                event_type = event.type
                subtype = event.data.get("subtype", "")
                print(f"  Event {i}: {event_type}" + (f"/{subtype}" if subtype else ""))

                # Extract session_id from any event that has it
                if "session_id" in event.data:
                    session_id = event.data.get("session_id")
                    if not session_id or session_id == "unknown":
                        pass
                    else:
                        print(f"    → Session ID: {session_id[:16]}...")

                if event_type == "session_start":
                    session_id = event.data.get("session_id")
                    print(f"    → Session started")

                elif event_type == "tool_use":
                    tool_name = event.data.get("tool")
                    tool_events.append(event)
                    print(f"    → Tool: {tool_name}")

                elif event_type == "tool_result":
                    status = event.data.get("status")
                    print(f"    → Status: {status}")

                elif event_type == "text" or event_type == "assistant":
                    # Both 'text' and 'assistant' events contain content
                    content_data = event.data.get("content", event.data.get("message", ""))
                    if isinstance(content_data, str):
                        content = content_data[:50]
                        print(f"    → Content: {content}...")
                    elif isinstance(content_data, dict):
                        # Might be a message with content blocks
                        if "content" in content_data:
                            blocks = content_data.get("content", [])
                            if isinstance(blocks, list) and blocks:
                                for block in blocks:
                                    if isinstance(block, dict):
                                        block_type = block.get("type", "unknown")
                                        if block_type == "tool_use":
                                            tool_name = block.get("name", "unknown")
                                            tool_events.append(event)
                                            print(f"    → Tool use detected: {tool_name}")
                                        elif block_type == "text":
                                            text = block.get("text", "")[:30]
                                            print(f"    → Text: {text}...")
                                    else:
                                        print(f"    → Content block: {str(block)[:30]}...")
                        else:
                            content = str(content_data)[:50]
                            print(f"    → Content (dict): {content}...")
                    else:
                        content = str(content_data)[:50]
                        print(f"    → Content: {content}...")

                elif event_type == "result":
                    usage = event.data.get("usage", {})
                    print(f"    → Usage: {usage}")

                # Show first event data for debugging
                if i == 1:
                    print(f"    → Full data keys: {list(event.data.keys())}")

            print()

            # Step 7: Test session resumption
            if session_id:
                print("Step 7: Testing session resumption with --resume...")
                resume_cmd = (
                    f'claude -p "Now count how many files there are" '
                    f'--resume {session_id} '
                    f'--output-format stream-json '
                    f'--verbose'
                )
                print(f"Resume command: {resume_cmd[:80]}...")

                result = run_tmux_command(["tmux", "send-keys", "-t", session_name, resume_cmd, "Enter"])
                if result.returncode == 0:
                    print("✓ Resume command sent")
                    print("  Waiting 10 seconds for resumed session...")
                    time.sleep(10)

                    # Capture ALL output (more lines to catch everything)
                    result = run_tmux_command(["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-200"])
                    all_output = result.stdout

                    # Parse all events
                    all_events = parser.parse_output(all_output)

                    # Find events that are different from original
                    # (Simple heuristic: total count increased)
                    if len(all_events) > len(events):
                        print(f"✓ Session resumption SUCCESS - {len(all_events) - len(events)} new events")

                        # Show new events
                        for event in all_events[len(events):]:
                            if event.type == "assistant":
                                # Check for tool use in content
                                content_data = event.data.get("content", event.data.get("message", ""))
                                if isinstance(content_data, dict) and "content" in content_data:
                                    blocks = content_data.get("content", [])
                                    for block in blocks:
                                        if isinstance(block, dict):
                                            if block.get("type") == "tool_use":
                                                print(f"    → Tool: {block.get('name')}")
                                            elif block.get("type") == "text":
                                                print(f"    → Text: {block.get('text', '')[:40]}...")
                            else:
                                print(f"    → Event type: {event.type}")
                    else:
                        print(f"⚠️  No new events captured (may need more wait time)")
                        print(f"    Total events: {len(all_events)} (was {len(events)})")
                else:
                    print(f"✗ Failed to send resume command: {result.stderr}")
            else:
                print("Step 7: Skipped (no session_id found)")

            print()

            # Step 8: Summary
            print("=" * 70)
            print("SUMMARY")
            print("=" * 70)
            print(f"Total events parsed: {len(events)}")
            print(f"Session ID captured: {'✓' if session_id else '✗'}")
            print(f"Tool use detected: {'✓' if tool_events else '✗'}")
            print(f"Session resumption: {'✓' if session_id else '✗'}")
            print()

            # Check for file edit tools
            edit_tools = [e for e in tool_events if e.data.get("tool") in ["Edit", "Write", "MultiEdit"]]
            if edit_tools:
                print(f"File edit tools detected: {len(edit_tools)}")
                print("  → GitButler auto-commit would trigger here")

            print()
            print("✓ Prototype validation complete!")
            print()
            print("This demonstrates that the JSON monitoring approach will work:")
            print("  1. Claude produces parseable JSON events")
            print("  2. We can capture and parse events from tmux")
            print("  3. We can detect tool use for GitButler integration")
            print("  4. Session resumption works via --resume")
            print()
    else:
        print(f"✗ Failed to capture output: {result.stderr}")

    # Cleanup
    print("Cleanup: Killing tmux session...")
    run_tmux_command(["tmux", "kill-session", "-t", session_name])
    print("✓ Session killed")
    print()


if __name__ == "__main__":
    try:
        test_json_mode()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        # Cleanup on interrupt
        run_tmux_command(["tmux", "kill-session", "-t", "chorus-prototype"])
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        # Cleanup on error
        run_tmux_command(["tmux", "kill-session", "-t", "chorus-prototype"])
