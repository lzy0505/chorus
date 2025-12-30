"""Tests for status poller service."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from sqlmodel import Session

from models import Task, TaskStatus, ClaudeStatus
from services.status_poller import StatusPoller


@pytest.fixture
def mock_detector():
    """Create a mock status detector."""
    with patch("services.status_poller.StatusDetector") as mock:
        yield mock.return_value


class TestStatusPoller:
    """Tests for StatusPoller class."""

    def test_initialization(self):
        """Test poller initialization."""
        poller = StatusPoller(interval=10.0)
        assert poller.interval == 10.0
        assert poller._running is False
        assert poller._correction_count == 0

    def test_default_interval(self):
        """Test default polling interval is 5 seconds (hybrid mode)."""
        poller = StatusPoller()
        assert poller.interval == 5.0

    @pytest.mark.asyncio
    async def test_poll_once_updates_changed_status(self, engine, mock_detector):
        """Test that poll_once updates status when detection differs."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return busy (different from idle)
        mock_detector.detect_status.return_value = ClaudeStatus.busy

        poller = StatusPoller(interval=5.0, engine=engine)
        poller.detector = mock_detector

        await poller._poll_once()

        # Verify status was updated
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.busy
            assert poller._correction_count == 1

    @pytest.mark.asyncio
    async def test_poll_once_skips_unchanged_status(self, engine, mock_detector):
        """Test that poll_once doesn't update when status matches."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return same status
        mock_detector.detect_status.return_value = ClaudeStatus.idle

        poller = StatusPoller(interval=5.0, engine=engine)
        poller.detector = mock_detector

        await poller._poll_once()

        # Verify status wasn't changed
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.idle
            assert poller._correction_count == 0

    @pytest.mark.asyncio
    async def test_poll_once_updates_task_status_when_waiting(self, engine, mock_detector):
        """Test that poll_once updates task status to waiting."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return waiting
        mock_detector.detect_status.return_value = ClaudeStatus.waiting

        poller = StatusPoller(interval=5.0, engine=engine)
        poller.detector = mock_detector

        await poller._poll_once()

        # Verify both statuses updated
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.waiting
            assert task.status == TaskStatus.waiting

    @pytest.mark.asyncio
    async def test_poll_once_skips_tasks_without_tmux(self, engine, mock_detector):
        """Test that poll_once skips tasks without tmux sessions."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
                tmux_session=None,  # No tmux session
            )
            db.add(task)
            db.commit()
            db.refresh(task)

        poller = StatusPoller(interval=5.0, engine=engine)
        poller.detector = mock_detector

        await poller._poll_once()

        # Detector should not be called
        mock_detector.detect_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_once_marks_stopped_when_session_not_found(self, engine, mock_detector):
        """Test that poll_once marks Claude as stopped when session doesn't exist."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return None (session not found)
        mock_detector.detect_status.return_value = None

        poller = StatusPoller(interval=5.0, engine=engine)
        poller.detector = mock_detector

        await poller._poll_once()

        # Verify status was marked as stopped and session cleared
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.stopped
            assert task.claude_session_id is None
            assert poller._orphan_cleanups == 1

    @pytest.mark.asyncio
    async def test_poll_once_handles_errors_gracefully(self, engine, mock_detector):
        """Test that poll_once doesn't crash on errors."""
        # Mock detector to raise exception
        mock_detector.detect_status.side_effect = Exception("Test error")

        poller = StatusPoller(interval=5.0)
        poller.detector = mock_detector

        # Should not raise
        await poller._poll_once()

    def test_get_stats(self):
        """Test get_stats returns polling statistics."""
        poller = StatusPoller(interval=7.5)
        poller._running = True
        poller._correction_count = 5

        stats = poller.get_stats()

        assert stats["running"] is True
        assert stats["interval"] == 7.5
        assert stats["correction_count"] == 5

    @pytest.mark.asyncio
    async def test_poll_now(self, mock_detector):
        """Test poll_now triggers immediate poll."""
        mock_detector.detect_status.return_value = ClaudeStatus.idle

        poller = StatusPoller(interval=5.0)
        poller.detector = mock_detector

        # Should call _poll_once
        await poller.poll_now()

        # Verify it actually polled (detector was called)
        mock_detector.detect_status.called

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Test starting and stopping the poller."""
        poller = StatusPoller(interval=0.1)  # Fast interval for testing

        # Start
        poller.start()
        assert poller._running is True
        assert poller._task is not None

        # Give it a moment to start
        import asyncio
        await asyncio.sleep(0.05)

        # Stop
        await poller.stop()
        assert poller._running is False

    def test_start_when_already_running(self):
        """Test that starting when already running is safe."""
        poller = StatusPoller(interval=5.0)
        poller._running = True

        # Should not crash
        poller.start()

        # Still running
        assert poller._running is True

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test that stopping when not running is safe."""
        poller = StatusPoller(interval=5.0)

        # Should not crash
        await poller.stop()


class TestStatusPollerGlobalInstance:
    """Tests for global poller instance management."""

    def test_get_status_poller_creates_instance(self):
        """Test that get_status_poller creates a poller."""
        from services.status_poller import get_status_poller, _poller

        # Clear global instance
        import services.status_poller as poller_module
        poller_module._poller = None

        poller = get_status_poller(interval=3.0)
        assert poller is not None
        assert poller.interval == 3.0

    def test_get_status_poller_returns_same_instance(self):
        """Test that get_status_poller returns the same instance."""
        from services.status_poller import get_status_poller

        poller1 = get_status_poller()
        poller2 = get_status_poller()

        assert poller1 is poller2
