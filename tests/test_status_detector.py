"""Tests for status detector service."""

import pytest
from unittest.mock import MagicMock, patch

from models import ClaudeStatus
from services.status_detector import StatusDetector
from services.tmux import SessionNotFoundError


class TestStatusDetector:
    """Tests for StatusDetector class."""

    def test_detect_idle_from_prompt(self):
        """Test detecting idle status from terminal prompt."""
        detector = StatusDetector()

        # Mock tmux to return output with prompt
        detector.tmux.capture_output = MagicMock(return_value="Some output\n> ")

        status = detector.detect_status(task_id=1)
        assert status == ClaudeStatus.idle

    def test_detect_idle_from_claude_prompt(self):
        """Test detecting idle status from claude> prompt."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(return_value="Done\nclaude> ")

        status = detector.detect_status(task_id=1)
        assert status == ClaudeStatus.idle

    def test_detect_waiting_from_permission_prompt(self):
        """Test detecting waiting status from permission prompts."""
        detector = StatusDetector()

        # Test various permission prompt patterns
        prompts = [
            "Allow write to file? (y/n)",
            "Do you want to proceed?",
            "Allow?",
            "Press Enter to continue",
        ]

        for prompt in prompts:
            detector.tmux.capture_output = MagicMock(return_value=prompt)
            status = detector.detect_status(task_id=1)
            assert status == ClaudeStatus.waiting, f"Should detect waiting in: {prompt}"

    def test_detect_busy_when_no_patterns_match(self):
        """Test detecting busy status when no patterns match."""
        detector = StatusDetector()

        # Output that doesn't match idle or waiting patterns
        detector.tmux.capture_output = MagicMock(
            return_value="Processing your request...\nThinking..."
        )

        status = detector.detect_status(task_id=1)
        assert status == ClaudeStatus.busy

    def test_detect_stopped_when_no_output(self):
        """Test detecting stopped status when terminal is empty."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(return_value="")

        status = detector.detect_status(task_id=1)
        assert status == ClaudeStatus.stopped

    def test_detect_returns_none_when_session_not_found(self):
        """Test that detect_status returns None when session doesn't exist."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(
            side_effect=SessionNotFoundError("Session not found")
        )

        status = detector.detect_status(task_id=1)
        assert status is None

    def test_waiting_pattern_priority_over_idle(self):
        """Test that waiting patterns take priority over idle patterns."""
        detector = StatusDetector()

        # Output with both prompt and permission request
        detector.tmux.capture_output = MagicMock(
            return_value="Some output\n> Allow write? (y/n)"
        )

        status = detector.detect_status(task_id=1)
        assert status == ClaudeStatus.waiting

    def test_is_claude_running_true(self):
        """Test detecting if Claude is running."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(
            return_value="claude> Working on your task"
        )

        assert detector.is_claude_running(task_id=1) is True

    def test_is_claude_running_false_empty(self):
        """Test detecting Claude not running when output is empty."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(return_value="")

        assert detector.is_claude_running(task_id=1) is False

    def test_is_claude_running_false_session_not_found(self):
        """Test detecting Claude not running when session doesn't exist."""
        detector = StatusDetector()

        detector.tmux.capture_output = MagicMock(
            side_effect=SessionNotFoundError("Session not found")
        )

        assert detector.is_claude_running(task_id=1) is False

    def test_analyze_last_lines_only(self):
        """Test that detector focuses on last few lines of output."""
        detector = StatusDetector()

        # Long output with busy text followed by prompt at end
        long_output = "\n".join([
            "Line 1",
            "Processing...",
            "Thinking...",
            "Working...",
        ] * 20) + "\n> "  # Prompt at the very end

        detector.tmux.capture_output = MagicMock(return_value=long_output)

        status = detector.detect_status(task_id=1)
        # Should detect idle from the prompt at the end
        assert status == ClaudeStatus.idle

    def test_custom_lines_parameter(self):
        """Test that custom lines parameter is passed to capture_output."""
        detector = StatusDetector()

        mock_capture = MagicMock(return_value="> ")
        detector.tmux.capture_output = mock_capture

        detector.detect_status(task_id=1, lines=100)

        mock_capture.assert_called_once_with(1, lines=100)
