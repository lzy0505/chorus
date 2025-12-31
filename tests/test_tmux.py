"""Tests for task-centric tmux service."""

import pytest
from unittest.mock import patch, MagicMock, call, mock_open
from uuid import UUID, uuid4
from pathlib import Path

from services.tmux import (
    TmuxService,
    TmuxError,
    SessionNotFoundError,
    SessionExistsError,
    SessionInfo,
    session_exists,
    _session_id_for_task,
    _run_tmux,
    get_transcript_dir,
    create_transcript_file,
)


class TestTranscriptFunctions:
    """Tests for transcript file management."""

    def test_get_transcript_dir(self):
        """Test getting transcript directory path."""
        task_id = UUID("12345678-1234-5678-1234-567812345678")
        expected = Path("/tmp/chorus/task-12345678-1234-5678-1234-567812345678")
        assert get_transcript_dir(task_id) == expected

    @patch("services.tmux.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    @patch("services.tmux.datetime")
    def test_create_transcript_file(self, mock_datetime, mock_file, mock_mkdir):
        """Test creating transcript file with minimal entry."""
        from datetime import datetime, timezone

        task_id = UUID("12345678-1234-5678-1234-567812345678")
        mock_now = datetime(2025, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        result = create_transcript_file(task_id, "/test/project")

        # Check directory creation
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # Check file was opened for writing
        expected_path = Path("/tmp/chorus/task-12345678-1234-5678-1234-567812345678/transcript.json")
        mock_file.assert_called_once_with(expected_path, "w")

        # Check returned path
        assert result == expected_path

        # Check JSON was written
        handle = mock_file()
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        assert '"sessionId": "12345678-1234-5678-1234-567812345678"' in written_data
        assert '"cwd": "/test/project"' in written_data


class TestSessionIdGeneration:
    """Tests for session ID generation."""

    def test_session_id_for_task(self):
        """Test generating session ID from task UUID."""
        task_id = UUID("12345678-1234-5678-1234-567812345678")
        assert _session_id_for_task(task_id) == "claude-task-12345678-1234-5678-1234-567812345678"

    def test_get_session_id(self):
        """Test TmuxService.get_session_id method."""
        service = TmuxService()
        task_id = UUID("12345678-1234-5678-1234-567812345678")
        assert service.get_session_id(task_id) == "claude-task-12345678-1234-5678-1234-567812345678"


class TestSessionExists:
    """Tests for session existence check."""

    @patch("services.tmux._run_tmux")
    def test_session_exists_true(self, mock_run):
        """Test when session exists."""
        mock_run.return_value = MagicMock(returncode=0)

        result = session_exists("claude-task-1")

        assert result is True
        mock_run.assert_called_once_with(
            ["has-session", "-t", "claude-task-1"], check=False
        )

    @patch("services.tmux._run_tmux")
    def test_session_exists_false(self, mock_run):
        """Test when session doesn't exist."""
        mock_run.return_value = MagicMock(returncode=1)

        result = session_exists("claude-task-1")

        assert result is False


class TestTmuxServiceCreateSession:
    """Tests for TmuxService.create_task_session."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_create_task_session_success(self, mock_run, mock_exists):
        """Test successful session creation."""
        mock_exists.return_value = False
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService(project_root="/test/project")
        session_id = service.create_task_session(42)

        assert session_id == "claude-task-42"
        mock_run.assert_called_once_with(
            [
                "new-session",
                "-d",
                "-s",
                "claude-task-42",
                "-c",
                "/test/project",
            ]
        )

    @patch("services.tmux.session_exists")
    def test_create_task_session_already_exists(self, mock_exists):
        """Test creating a session that already exists."""
        mock_exists.return_value = True

        service = TmuxService()

        with pytest.raises(SessionExistsError) as exc_info:
            service.create_task_session(42)

        assert "already exists" in str(exc_info.value)


class TestTmuxServiceStartClaude:
    """Tests for TmuxService.start_claude."""

    @patch("services.tmux.os.environ.get")
    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_start_claude_success(self, mock_run, mock_exists, mock_env_get):
        """Test starting Claude in existing session with shared config."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        mock_env_get.return_value = None  # No OAuth token

        service = TmuxService()
        service.start_claude(42)

        # Claude should be launched with CLAUDE_CONFIG_DIR pointing to shared hooks config
        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42",
             'CLAUDE_CONFIG_DIR="/tmp/chorus/hooks/.claude" claude', "Enter"]
        )

    @patch("services.tmux._session_id_for_task")
    @patch("services.tmux.os.environ.get")
    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_start_claude_with_prompt(self, mock_run, mock_exists, mock_env_get, mock_session_id):
        """Test starting Claude with initial prompt."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        mock_env_get.return_value = None  # No OAuth token
        mock_session_id.return_value = "claude-task-42"  # Use consistent session ID

        service = TmuxService()
        service.start_claude(42, initial_prompt="Hello Claude")

        # Should call send-keys once with prompt included as argument to claude
        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42",
             'CLAUDE_CONFIG_DIR="/tmp/chorus/hooks/.claude" claude "Hello Claude"', "Enter"]
        )

    @patch("services.tmux.session_exists")
    def test_start_claude_no_session(self, mock_exists):
        """Test starting Claude when session doesn't exist."""
        mock_exists.return_value = False

        service = TmuxService()

        with pytest.raises(SessionNotFoundError) as exc_info:
            service.start_claude(42)

        assert "not found" in str(exc_info.value)


class TestTmuxServiceRestartClaude:
    """Tests for TmuxService.restart_claude."""

    @patch("services.tmux.os.environ.get")
    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    @patch("services.tmux.time.sleep")
    def test_restart_claude_success(self, mock_sleep, mock_run, mock_exists, mock_env_get):
        """Test restarting Claude with shared config."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        mock_env_get.return_value = None  # No OAuth token

        service = TmuxService()
        service.restart_claude(42)

        # Should send Ctrl-C twice, then restart with shared config
        calls = mock_run.call_args_list
        assert len(calls) == 3
        assert calls[0] == call(["send-keys", "-t", "claude-task-42", "C-c"])
        assert calls[1] == call(["send-keys", "-t", "claude-task-42", "C-c"])
        assert calls[2] == call(
            ["send-keys", "-t", "claude-task-42",
             'CLAUDE_CONFIG_DIR="/tmp/chorus/hooks/.claude" claude', "Enter"]
        )

    @patch("services.tmux.session_exists")
    def test_restart_claude_no_session(self, mock_exists):
        """Test restarting Claude when session doesn't exist."""
        mock_exists.return_value = False

        service = TmuxService()

        with pytest.raises(SessionNotFoundError):
            service.restart_claude(42)


class TestTmuxServiceKillSession:
    """Tests for TmuxService.kill_task_session."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_kill_task_session_success(self, mock_run, mock_exists):
        """Test killing a task session."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService()
        service.kill_task_session(42)

        mock_run.assert_called_once_with(
            ["kill-session", "-t", "claude-task-42"]
        )

    @patch("services.tmux.session_exists")
    def test_kill_task_session_not_found(self, mock_exists):
        """Test killing a non-existent session."""
        mock_exists.return_value = False

        service = TmuxService()

        with pytest.raises(SessionNotFoundError):
            service.kill_task_session(42)


class TestTmuxServiceCaptureOutput:
    """Tests for TmuxService.capture_output."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_capture_output_success(self, mock_run, mock_exists):
        """Test capturing output from session."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Hello from Claude\n>"
        )

        service = TmuxService()
        output = service.capture_output(42, lines=50)

        assert output == "Hello from Claude\n>"
        mock_run.assert_called_once_with(
            ["capture-pane", "-t", "claude-task-42", "-p", "-S", "-50"],
            check=False,
        )

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_capture_output_default_lines(self, mock_run, mock_exists):
        """Test capture with default line count."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="output")

        service = TmuxService()
        service.capture_output(42)

        # Default is 100 lines
        call_args = mock_run.call_args[0][0]
        assert "-100" in call_args

    @patch("services.tmux.session_exists")
    def test_capture_output_no_session(self, mock_exists):
        """Test capturing from non-existent session."""
        mock_exists.return_value = False

        service = TmuxService()

        with pytest.raises(SessionNotFoundError):
            service.capture_output(42)


class TestTmuxServiceSendKeys:
    """Tests for TmuxService.send_keys."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_send_keys_with_enter(self, mock_run, mock_exists):
        """Test sending keys with Enter."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService()
        service.send_keys(42, "Hello Claude")

        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42", "Hello Claude", "Enter"]
        )

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_send_keys_without_enter(self, mock_run, mock_exists):
        """Test sending keys without Enter."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService()
        service.send_keys(42, "partial", enter=False)

        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42", "partial"]
        )

    @patch("services.tmux.session_exists")
    def test_send_keys_no_session(self, mock_exists):
        """Test sending keys to non-existent session."""
        mock_exists.return_value = False

        service = TmuxService()

        with pytest.raises(SessionNotFoundError):
            service.send_keys(42, "Hello")


class TestTmuxServiceSendConfirmation:
    """Tests for TmuxService.send_confirmation."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_send_confirmation_yes(self, mock_run, mock_exists):
        """Test sending yes confirmation."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService()
        service.send_confirmation(42, confirm=True)

        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42", "y", "Enter"]
        )

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_send_confirmation_no(self, mock_run, mock_exists):
        """Test sending no confirmation."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        service = TmuxService()
        service.send_confirmation(42, confirm=False)

        mock_run.assert_called_once_with(
            ["send-keys", "-t", "claude-task-42", "n", "Enter"]
        )


class TestTmuxServiceGetSessionInfo:
    """Tests for TmuxService.get_session_info."""

    @patch("services.tmux.session_exists")
    @patch("services.tmux._run_tmux")
    def test_get_session_info_exists(self, mock_run, mock_exists):
        """Test getting info for existing session."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Hello\n>"
        )

        service = TmuxService()
        info = service.get_session_info(42)

        assert info.session_id == "claude-task-42"
        assert info.task_id == 42
        assert info.exists is True
        assert info.has_claude_process is True  # '>' in output

    @patch("services.tmux.session_exists")
    def test_get_session_info_not_exists(self, mock_exists):
        """Test getting info for non-existent session."""
        mock_exists.return_value = False

        service = TmuxService()
        info = service.get_session_info(42)

        assert info.session_id == "claude-task-42"
        assert info.task_id == 42
        assert info.exists is False
        assert info.has_claude_process is False


class TestTmuxServiceListSessions:
    """Tests for TmuxService.list_task_sessions."""

    @patch("services.tmux._run_tmux")
    def test_list_task_sessions(self, mock_run):
        """Test listing task sessions."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-task-1\nclaude-task-42\nother-session\nclaude-feature\n",
        )

        service = TmuxService()
        task_ids = service.list_task_sessions()

        assert task_ids == [1, 42]

    @patch("services.tmux._run_tmux")
    def test_list_task_sessions_empty(self, mock_run):
        """Test listing when no task sessions exist."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        service = TmuxService()
        task_ids = service.list_task_sessions()

        assert task_ids == []

    @patch("services.tmux._run_tmux")
    def test_list_task_sessions_filters_invalid(self, mock_run):
        """Test that invalid session names are filtered."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-task-abc\nclaude-task-1\nclaude-task-\n",
        )

        service = TmuxService()
        task_ids = service.list_task_sessions()

        # Only valid integer task IDs
        assert task_ids == [1]


class TestSessionInfo:
    """Tests for SessionInfo dataclass."""

    def test_session_info_creation(self):
        """Test creating SessionInfo."""
        info = SessionInfo(
            session_id="claude-task-1",
            task_id=1,
            exists=True,
            has_claude_process=True,
        )

        assert info.session_id == "claude-task-1"
        assert info.task_id == 1
        assert info.exists is True
        assert info.has_claude_process is True

    def test_session_info_defaults(self):
        """Test SessionInfo default values."""
        info = SessionInfo(
            session_id="claude-task-1",
            task_id=1,
            exists=False,
        )

        assert info.has_claude_process is False


class TestExceptions:
    """Tests for custom exceptions."""

    def test_tmux_error_hierarchy(self):
        """Test exception inheritance."""
        assert issubclass(SessionNotFoundError, TmuxError)
        assert issubclass(SessionExistsError, TmuxError)

    def test_exception_messages(self):
        """Test exception messages."""
        e1 = SessionNotFoundError("Session not found")
        assert str(e1) == "Session not found"

        e2 = SessionExistsError("Session exists")
        assert str(e2) == "Session exists"


# Integration tests - these actually run tmux commands
# Mark with 'integration' to skip in CI environments


@pytest.mark.integration
class TestTmuxServiceIntegration:
    """Integration tests that actually run tmux commands.

    These tests require tmux to be installed and available.
    Run with: pytest -m integration
    """

    @pytest.fixture
    def service(self, tmp_path):
        """Create a TmuxService with temp project root."""
        return TmuxService(project_root=str(tmp_path))

    @pytest.fixture
    def cleanup_sessions(self, service):
        """Cleanup any test sessions after tests."""
        yield
        # Clean up any sessions created during tests
        for task_id in service.list_task_sessions():
            try:
                service.kill_task_session(task_id)
            except SessionNotFoundError:
                pass

    def test_full_session_lifecycle(self, service, cleanup_sessions):
        """Test creating, using, and killing a session."""
        task_id = 99999  # Use high ID to avoid conflicts

        # Create session
        session_id = service.create_task_session(task_id)
        assert session_id == "claude-task-99999"
        assert service.session_exists(task_id)

        # Capture output (should have shell prompt)
        output = service.capture_output(task_id)
        assert output is not None

        # Send a simple command
        service.send_keys(task_id, "echo 'hello test'")

        # Wait a bit and capture output
        import time
        time.sleep(0.5)
        output = service.capture_output(task_id)
        assert "hello test" in output

        # Kill session
        service.kill_task_session(task_id)
        assert not service.session_exists(task_id)

    def test_session_exists_check(self, service, cleanup_sessions):
        """Test session existence checking."""
        task_id = 99998

        assert not service.session_exists(task_id)

        service.create_task_session(task_id)
        assert service.session_exists(task_id)

        service.kill_task_session(task_id)
        assert not service.session_exists(task_id)

    def test_list_task_sessions(self, service, cleanup_sessions):
        """Test listing task sessions."""
        task_ids = [99997, 99996]

        for tid in task_ids:
            service.create_task_session(tid)

        listed = service.list_task_sessions()
        for tid in task_ids:
            assert tid in listed

        # Cleanup
        for tid in task_ids:
            service.kill_task_session(tid)
