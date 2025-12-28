"""Tests for service modules."""

import pytest
from unittest.mock import patch, MagicMock

from services.tmux import (
    create_session,
    kill_session,
    list_sessions,
    capture_output,
    send_keys,
    send_confirmation,
)


class TestTmuxService:
    """Tests for tmux service functions."""

    @patch("services.tmux.subprocess.run")
    def test_create_session(self, mock_run):
        """Test creating a tmux session."""
        mock_run.return_value = MagicMock(returncode=0)

        session_id = create_session("test")

        assert session_id == "claude-test"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "tmux" in call_args
        assert "new-session" in call_args
        assert "claude-test" in call_args

    @patch("services.tmux.subprocess.run")
    def test_create_session_with_prompt(self, mock_run):
        """Test creating a session with initial prompt."""
        mock_run.return_value = MagicMock(returncode=0)

        session_id = create_session("test", initial_prompt="Hello")

        assert session_id == "claude-test"
        # Should be called twice: create + send_keys
        assert mock_run.call_count == 2

    @patch("services.tmux.subprocess.run")
    def test_kill_session(self, mock_run):
        """Test killing a tmux session."""
        mock_run.return_value = MagicMock(returncode=0)

        kill_session("claude-test")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "kill-session" in call_args
        assert "claude-test" in call_args

    @patch("services.tmux.subprocess.run")
    def test_list_sessions(self, mock_run):
        """Test listing tmux sessions."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-auth\nclaude-api\nother-session\n"
        )

        sessions = list_sessions()

        assert sessions == ["claude-auth", "claude-api"]
        assert "other-session" not in sessions

    @patch("services.tmux.subprocess.run")
    def test_list_sessions_empty(self, mock_run):
        """Test listing sessions when none exist."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        sessions = list_sessions()

        assert sessions == []

    @patch("services.tmux.subprocess.run")
    def test_capture_output(self, mock_run):
        """Test capturing terminal output."""
        expected_output = "> some output\n> more output"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=expected_output
        )

        output = capture_output("claude-test", lines=50)

        assert output == expected_output
        call_args = mock_run.call_args[0][0]
        assert "capture-pane" in call_args
        assert "-50" in call_args

    @patch("services.tmux.subprocess.run")
    def test_send_keys(self, mock_run):
        """Test sending text to session."""
        mock_run.return_value = MagicMock(returncode=0)

        send_keys("claude-test", "Hello Claude")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "send-keys" in call_args
        assert "Hello Claude" in call_args
        assert "Enter" in call_args

    @patch("services.tmux.subprocess.run")
    def test_send_confirmation_yes(self, mock_run):
        """Test sending yes confirmation."""
        mock_run.return_value = MagicMock(returncode=0)

        send_confirmation("claude-test", confirm=True)

        call_args = mock_run.call_args[0][0]
        assert "y" in call_args

    @patch("services.tmux.subprocess.run")
    def test_send_confirmation_no(self, mock_run):
        """Test sending no confirmation."""
        mock_run.return_value = MagicMock(returncode=0)

        send_confirmation("claude-test", confirm=False)

        call_args = mock_run.call_args[0][0]
        assert "n" in call_args


class TestStatusDetection:
    """Tests for status detection patterns."""

    def test_idle_pattern_detection(self):
        """Test detecting idle status from output."""
        import re
        from config import STATUS_PATTERNS

        idle_outputs = [
            "some output\n>",
            "done processing\n> ",
            "finished\nclaude> ",
        ]

        for output in idle_outputs:
            last_lines = output.split("\n")[-5:]
            is_idle = any(
                re.search(pattern, "\n".join(last_lines))
                for pattern in STATUS_PATTERNS["idle"]
            )
            assert is_idle, f"Should detect idle in: {output!r}"

    def test_waiting_pattern_detection(self):
        """Test detecting waiting status from output."""
        import re
        from config import STATUS_PATTERNS

        waiting_outputs = [
            "Allow write to file? (y/n)",
            "Do you want to proceed?",
            "Allow?",
            "Continue?",
        ]

        for output in waiting_outputs:
            is_waiting = any(
                re.search(pattern, output)
                for pattern in STATUS_PATTERNS["waiting"]
            )
            assert is_waiting, f"Should detect waiting in: {output!r}"

    def test_busy_is_default(self):
        """Test that busy is the default status."""
        import re
        from config import STATUS_PATTERNS

        busy_output = "Processing request...\nWorking on task..."

        is_idle = any(
            re.search(pattern, busy_output)
            for pattern in STATUS_PATTERNS["idle"]
        )
        is_waiting = any(
            re.search(pattern, busy_output)
            for pattern in STATUS_PATTERNS["waiting"]
        )

        assert not is_idle
        assert not is_waiting
