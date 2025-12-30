"""Tests for JSON event parser."""

import pytest
from services.json_parser import JsonEventParser, ClaudeJsonEvent


class TestJsonEventParser:
    """Test JSON event parsing functionality."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance."""
        return JsonEventParser()

    def test_parse_valid_json_line(self, parser):
        """Test parsing a valid JSON line."""
        line = '{"type": "session_start", "session_id": "abc123"}'
        event = parser.parse_line(line)

        assert event is not None
        assert event.event_type == "session_start"
        assert event.session_id == "abc123"
        assert event.data["type"] == "session_start"

    def test_parse_invalid_json_line(self, parser):
        """Test parsing invalid JSON returns None."""
        line = 'not valid json'
        event = parser.parse_line(line)
        assert event is None

    def test_parse_empty_line(self, parser):
        """Test parsing empty line returns None."""
        event = parser.parse_line("")
        assert event is None

    def test_parse_non_json_text(self, parser):
        """Test parsing regular text returns None."""
        line = "This is regular terminal output"
        event = parser.parse_line(line)
        assert event is None

    def test_parse_multiple_events(self, parser):
        """Test parsing multiple JSON events from output."""
        output = '''
{"type": "session_start", "session_id": "abc123"}
{"type": "tool_use", "tool": "Read", "status": "running"}
{"type": "tool_result", "tool": "Read", "status": "success"}
'''
        events = parser.parse_output(output)

        assert len(events) == 3
        assert events[0].event_type == "session_start"
        assert events[1].event_type == "tool_use"
        assert events[2].event_type == "tool_result"

    def test_parse_mixed_content(self, parser):
        """Test parsing output with mixed JSON and text."""
        output = '''
Some text output
{"type": "tool_use", "tool": "Bash"}
More text
{"type": "tool_result", "status": "success"}
'''
        events = parser.parse_output(output)

        assert len(events) == 2
        assert events[0].event_type == "tool_use"
        assert events[1].event_type == "tool_result"

    def test_parse_wrapped_json(self, parser):
        """Test parsing JSON that was wrapped by terminal."""
        output = '''
{"type": "tool_use",
"tool": "Read",
"file": "test.py"}
'''
        events = parser.parse_output(output)

        assert len(events) == 1
        assert events[0].event_type == "tool_use"

    def test_parse_empty_output(self, parser):
        """Test parsing empty output returns empty list."""
        events = parser.parse_output("")
        assert events == []

    def test_parse_no_json_in_output(self, parser):
        """Test parsing output with no JSON returns empty list."""
        output = "Just regular terminal output\nno JSON here"
        events = parser.parse_output(output)
        assert events == []

    def test_event_without_session_id(self, parser):
        """Test parsing event without session_id field."""
        line = '{"type": "tool_use", "tool": "Bash"}'
        event = parser.parse_line(line)

        assert event is not None
        assert event.event_type == "tool_use"
        assert event.session_id is None

    def test_malformed_json_skipped(self, parser):
        """Test that malformed JSON is skipped without breaking parsing."""
        output = '''
{"type": "valid_event"}
{malformed json
{"type": "another_valid_event"}
'''
        events = parser.parse_output(output)

        assert len(events) == 2
        assert events[0].event_type == "valid_event"
        assert events[1].event_type == "another_valid_event"

    def test_parse_complex_event_data(self, parser):
        """Test parsing event with complex nested data."""
        line = '{"type": "tool_result", "data": {"nested": {"field": "value"}}, "session_id": "xyz"}'
        event = parser.parse_line(line)

        assert event is not None
        assert event.event_type == "tool_result"
        assert event.session_id == "xyz"
        assert event.data["data"]["nested"]["field"] == "value"
