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
