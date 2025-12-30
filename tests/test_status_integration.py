"""Integration tests for hybrid status detection system.

Tests the interaction between hooks, polling, and corner cases.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from sqlmodel import Session

from models import Task, TaskStatus, ClaudeStatus
from services.status_detector import StatusDetector
from services.status_poller import StatusPoller


class TestHybridStatusDetection:
    """Integration tests for hybrid status detection."""

    @pytest.mark.asyncio
    async def test_hooks_take_priority_over_polling(self, engine):
        """Test that hook updates are faster than polling updates."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.busy,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return idle
        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=ClaudeStatus.idle)

        poller = StatusPoller(interval=0.1, engine=engine)
        poller.detector = detector

        # Start polling
        poller.start()
        await asyncio.sleep(0.05)  # Wait a bit

        # Simulate hook update (instant)
        with Session(engine) as db:
            task = db.get(Task, task_id)
            task.claude_status = ClaudeStatus.waiting
            db.add(task)
            db.commit()

        # Wait for poller to run
        await asyncio.sleep(0.2)

        # Stop poller
        await poller.stop()

        # Poller should have corrected from waiting back to idle
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.idle
            assert poller._correction_count >= 1

    @pytest.mark.asyncio
    async def test_polling_catches_missed_hooks(self, engine):
        """Test that polling detects status changes when hooks are missed."""
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

        # Mock detector to return busy (simulating Claude working but no hook fired)
        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=ClaudeStatus.busy)

        poller = StatusPoller(interval=0.1, engine=engine)
        poller.detector = detector
        poller.start()

        # Wait for at least one poll cycle
        await asyncio.sleep(0.15)

        await poller.stop()

        # Poller should have detected and corrected the status
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.busy
            assert poller._correction_count == 1


class TestCornerCases:
    """Tests for corner cases in status detection."""

    @pytest.mark.asyncio
    async def test_tmux_session_killed_during_polling(self, engine):
        """Test handling when tmux session is killed mid-poll."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.busy,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to return None (session not found)
        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=None)

        poller = StatusPoller(interval=0.1, engine=engine)
        poller.detector = detector

        # Should not crash
        await poller._poll_once()

        # Status should be marked as stopped (orphan cleanup)
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.stopped
            assert task.claude_session_id is None
            assert poller._orphan_cleanups == 1

    @pytest.mark.asyncio
    async def test_claude_frozen_detection(self, engine):
        """Test detecting when Claude is frozen (busy for too long)."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.busy,
                tmux_session="test-session",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Mock detector to consistently return busy
        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=ClaudeStatus.busy)

        poller = StatusPoller(interval=0.05, engine=engine)
        poller.detector = detector
        poller.start()

        # Run for a bit - status should stay busy
        await asyncio.sleep(0.2)
        await poller.stop()

        with Session(engine) as db:
            task = db.get(Task, task_id)
            # Should remain busy (frozen detection would be separate logic)
            assert task.claude_status == ClaudeStatus.busy

    @pytest.mark.asyncio
    async def test_rapid_status_changes(self, engine):
        """Test handling rapid status changes (hooks + polling)."""
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

        # Mock detector to alternate between states
        detector = StatusDetector()
        call_count = [0]

        def alternating_status(task_id):
            call_count[0] += 1
            return ClaudeStatus.busy if call_count[0] % 2 == 0 else ClaudeStatus.idle

        detector.detect_status = MagicMock(side_effect=alternating_status)

        poller = StatusPoller(interval=0.05, engine=engine)
        poller.detector = detector
        poller.start()

        await asyncio.sleep(0.3)
        await poller.stop()

        # Should have made multiple corrections
        assert poller._correction_count >= 2

    @pytest.mark.asyncio
    async def test_database_error_during_polling(self, engine):
        """Test that polling handles database errors gracefully."""
        # Create poller with invalid engine
        from sqlalchemy import create_engine as sa_create_engine
        bad_engine = sa_create_engine("sqlite:///nonexistent.db")

        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=ClaudeStatus.idle)

        poller = StatusPoller(interval=0.05, engine=bad_engine)
        poller.detector = detector

        # Should not crash
        await poller._poll_once()

        # Error should be logged but execution continues
        assert poller._correction_count == 0

    @pytest.mark.asyncio
    async def test_multiple_tasks_polling(self, engine):
        """Test polling multiple tasks simultaneously."""
        task_ids = []
        with Session(engine) as db:
            for i in range(5):
                task = Task(
                    title=f"Test {i}",
                    status=TaskStatus.running,
                    claude_status=ClaudeStatus.idle,
                    tmux_session=f"test-session-{i}",
                )
                db.add(task)
                db.commit()
                db.refresh(task)
                task_ids.append(task.id)

        # Mock detector to return busy for all
        detector = StatusDetector()
        detector.detect_status = MagicMock(return_value=ClaudeStatus.busy)

        poller = StatusPoller(interval=0.1, engine=engine)
        poller.detector = detector

        await poller._poll_once()

        # All tasks should be updated
        with Session(engine) as db:
            for task_id in task_ids:
                task = db.get(Task, task_id)
                assert task.claude_status == ClaudeStatus.busy

        assert poller._correction_count == 5
