"""Tests for desktop notification service."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from services.notifier import NotifierService, NotificationLevel


class TestNotifierService:
    """Test NotifierService functionality."""

    def test_init_default(self):
        """Test default initialization."""
        notifier = NotifierService()
        assert notifier.enabled is True

    def test_init_disabled(self):
        """Test initialization with notifications disabled."""
        notifier = NotifierService(enabled=False)
        assert notifier.enabled is False

    def test_send_when_disabled(self):
        """Test that no notification is sent when disabled."""
        notifier = NotifierService(enabled=False)

        with patch.object(notifier, "_send_macos") as mock_send:
            result = notifier.send("Test", "Message")

            assert result is False
            mock_send.assert_not_called()

    @patch("platform.system")
    def test_send_macos(self, mock_platform):
        """Test sending notification on macOS."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.send("Test Title", "Test Message")

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "osascript"
            assert "Test Title" in args[2]
            assert "Test Message" in args[2]

    @patch("platform.system")
    def test_send_macos_with_sound(self, mock_platform):
        """Test sending notification on macOS with sound."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.send("Test", "Message", sound=True)

            assert result is True
            args = mock_run.call_args[0][0]
            assert 'sound name "default"' in args[2]

    @patch("platform.system")
    def test_send_linux(self, mock_platform):
        """Test sending notification on Linux."""
        mock_platform.return_value = "Linux"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.send(
                "Test Title",
                "Test Message",
                level=NotificationLevel.WARNING
            )

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "notify-send"
            assert "Test Title" in args
            assert "Test Message" in args

    @patch("platform.system")
    def test_send_windows(self, mock_platform):
        """Test sending notification on Windows."""
        mock_platform.return_value = "Windows"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.send("Test Title", "Test Message")

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "powershell"

    @patch("platform.system")
    def test_send_unsupported_platform(self, mock_platform):
        """Test handling of unsupported platform."""
        mock_platform.return_value = "FreeBSD"
        notifier = NotifierService()

        result = notifier.send("Test", "Message")

        assert result is False

    @patch("platform.system")
    def test_send_subprocess_error(self, mock_platform):
        """Test handling of subprocess errors."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 5)

            result = notifier.send("Test", "Message")

            assert result is False

    @patch("platform.system")
    def test_send_nonzero_returncode(self, mock_platform):
        """Test handling of non-zero return code."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Error message"
            )

            result = notifier.send("Test", "Message")

            assert result is False


class TestConvenienceMethods:
    """Test convenience methods for common notifications."""

    @patch("platform.system")
    def test_task_started(self, mock_platform):
        """Test task started notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.task_started(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Task Started" in args[2]
            assert "Task #123" in args[2]
            assert "Test Task" in args[2]

    @patch("platform.system")
    def test_task_completed(self, mock_platform):
        """Test task completed notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.task_completed(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Task Completed" in args[2]
            assert "Task #123" in args[2]
            # Should have sound
            assert 'sound name "default"' in args[2]

    @patch("platform.system")
    def test_task_failed(self, mock_platform):
        """Test task failed notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.task_failed(123, "Test Task", "Error occurred")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Task Failed" in args[2]
            assert "Task #123" in args[2]
            assert "Error occurred" in args[2]
            # Should have sound
            assert 'sound name "default"' in args[2]

    @patch("platform.system")
    def test_task_failed_no_reason(self, mock_platform):
        """Test task failed notification without reason."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.task_failed(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Task Failed" in args[2]
            assert "Task #123" in args[2]

    @patch("platform.system")
    def test_claude_idle(self, mock_platform):
        """Test Claude idle notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.claude_idle(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Claude is Idle" in args[2]
            assert "ready for input" in args[2]

    @patch("platform.system")
    def test_permission_requested(self, mock_platform):
        """Test permission requested notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.permission_requested(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Permission Required" in args[2]
            assert "needs approval" in args[2]
            # Should have sound
            assert 'sound name "default"' in args[2]

    @patch("platform.system")
    def test_claude_crashed(self, mock_platform):
        """Test Claude crashed notification."""
        mock_platform.return_value = "Darwin"
        notifier = NotifierService()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = notifier.claude_crashed(123, "Test Task")

            assert result is True
            args = mock_run.call_args[0][0]
            assert "Claude Stopped" in args[2]
            assert "has stopped" in args[2]
            # Should have sound
            assert 'sound name "default"' in args[2]
