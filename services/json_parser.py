"""JSON event parser for Claude CLI stream-json output.

This module handles parsing of structured JSON events from Claude Code
when running with --output-format stream-json flag.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ClaudeJsonEvent:
    """Parsed JSON event from Claude CLI."""
    event_type: str
    data: dict
    session_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ClaudeJsonEvent":
        """Create event from parsed JSON dict."""
        return cls(
            event_type=data.get("type", "unknown"),
            data=data,
            session_id=data.get("session_id")
        )


class JsonEventParser:
    """Parser for Claude CLI JSON events."""

    def parse_line(self, line: str) -> Optional[ClaudeJsonEvent]:
        """Parse a single line as a JSON event.

        Args:
            line: A line of text that may contain JSON

        Returns:
            ClaudeJsonEvent if valid JSON found, None otherwise
        """
        line = line.strip()
        if not line or not line.startswith('{'):
            return None

        try:
            data = json.loads(line)
            return ClaudeJsonEvent.from_dict(data)
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse JSON line: {e}")
            return None

    def parse_output(self, output: str) -> list[ClaudeJsonEvent]:
        """Parse multiple lines of JSON events from tmux output.

        Handles terminal line wrapping by joining lines that appear to be
        continuation of JSON objects.

        Args:
            output: Multi-line string from tmux capture-pane

        Returns:
            List of parsed ClaudeJsonEvent objects
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
            # Continuation of current JSON (has content but doesn't start with {)
            elif current_json and stripped and not stripped.startswith('{'):
                # Try to continue the JSON (might be wrapped)
                # But first check if current_json is already complete
                try:
                    json.loads(current_json)
                    # Current JSON is complete, parse it
                    event = self.parse_line(current_json)
                    if event:
                        events.append(event)
                    current_json = ""
                except json.JSONDecodeError:
                    # Not complete, continue appending
                    current_json += stripped
            elif stripped == "" and current_json:
                # Empty line, but we have current JSON - try to parse it
                event = self.parse_line(current_json)
                if event:
                    events.append(event)
                current_json = ""

        # Parse last JSON
        if current_json:
            event = self.parse_line(current_json)
            if event:
                events.append(event)

        logger.debug(f"Parsed {len(events)} JSON events from {len(lines)} lines")
        return events

    @staticmethod
    def detect_permission_denial(event: ClaudeJsonEvent) -> Optional[dict]:
        """Detect permission denial from Claude output and extract denied tool/command.

        Looks for patterns like:
        - "I need permission to use the Bash tool"
        - "Claude requested permissions to use Bash"
        - "Error: Claude requested permissions to use Bash, but you haven't granted it yet"

        Args:
            event: Claude JSON event (typically from 'assistant' or 'result' messages)

        Returns:
            Dict with 'tool' and optionally 'command' if permission denial detected, None otherwise
        """
        import re

        # Extract text content from various event types
        text_content = None

        if event.event_type == "assistant":
            # Check message content
            message = event.data.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                # Join all text blocks
                text_content = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            elif isinstance(content, str):
                text_content = content

        elif event.event_type == "result":
            # Check result text
            result = event.data.get("result")
            if isinstance(result, str):
                text_content = result
            elif isinstance(result, dict):
                text_content = result.get("text", "")

        if not text_content:
            return None

        # Permission denial patterns
        patterns = [
            # "I need permission to use the Bash tool"
            r"(?:need|require)s?\s+permission\s+to\s+use\s+(?:the\s+)?(\w+)\s+tool",

            # "Claude requested permissions to use Bash"
            r"requested\s+permissions?\s+to\s+use\s+(\w+)",

            # "Error: Claude requested permissions to use Bash, but you haven't granted it"
            r"Error:.*?requested\s+permissions?\s+to\s+use\s+(\w+)",

            # "The Write tool requires permission"
            r"(?:The\s+)?(\w+)\s+tool\s+requires?\s+permission",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                tool_name = match.group(1)

                # Try to extract specific command for Bash
                command = None
                if tool_name.lower() == "bash":
                    # Look for command patterns
                    cmd_patterns = [
                        r"to\s+run\s+[`']([^`']+)[`']",
                        r"to\s+execute\s+[`']([^`']+)[`']",
                        r"command:\s*[`']?([^`'\n]+)[`']?",
                    ]
                    for cmd_pattern in cmd_patterns:
                        cmd_match = re.search(cmd_pattern, text_content, re.IGNORECASE)
                        if cmd_match:
                            command = cmd_match.group(1).strip()
                            break

                return {
                    "tool": tool_name,
                    "command": command,
                    "message": text_content[:200],  # Include snippet for context
                }

        return None
