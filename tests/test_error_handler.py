"""Tests for error handling functionality."""

import pytest
from unittest.mock import Mock, patch
from sqlmodel import Session, create_engine, SQLModel

from services.error_handler import (
    ServiceError,
    RecoverableError,
    UnrecoverableError,
    TaskRecovery,
    log_service_error,
)
from services.tmux import SessionNotFoundError, SessionExistsError
from services.gitbutler import GitButlerError, StackExistsError
from models import Task, TaskStatus, ClaudeStatus


@pytest.fixture
def db_session():
    """Create an in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestExceptionClasses:
    """Test custom exception classes."""

    def test_service_error(self):
        error = ServiceError("test error")
        assert str(error) == "test error"
        assert isinstance(error, Exception)

    def test_recoverable_error(self):
        error = RecoverableError("recoverable")
        assert isinstance(error, ServiceError)

    def test_unrecoverable_error(self):
        error = UnrecoverableError("unrecoverable")
        assert isinstance(error, ServiceError)


class TestLogServiceError:
    """Test service error logging."""

    def test_log_basic_error(self, caplog):
        error = ValueError("test error")
        log_service_error("tmux", "create_session", error)

        assert "Service error in tmux.create_session" in caplog.text
        assert "test error" in caplog.text

    def test_log_with_task_id(self, caplog):
        error = ValueError("test error")
        log_service_error("tmux", "create_session", error, task_id=123)

        # Check that task_id is included in the log record
        for record in caplog.records:
            if "task_id" in record.__dict__:
                assert record.__dict__["task_id"] == 123
                break
        else:
            pytest.fail("task_id not found in log record")

    def test_log_with_extra_context(self, caplog):
        error = ValueError("test error")
        extra = {"session_id": "tmux-1", "attempt": 2}
        log_service_error("gitbutler", "commit", error, extra=extra)

        # Check that extra context is included
        for record in caplog.records:
            if "session_id" in record.__dict__:
                assert record.__dict__["session_id"] == "tmux-1"
                assert record.__dict__["attempt"] == 2
                break
        else:
            pytest.fail("extra context not found in log record")


class TestTaskRecovery:
    """Test task recovery functionality."""

    def test_recover_from_tmux_failure_session_not_exists(self, db_session):
        """Test recovery when tmux session doesn't exist."""
        task = Task(title="Test Task", status=TaskStatus.running)
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        with patch("services.error_handler.TmuxService") as mock_tmux:
            mock_tmux.return_value.session_exists.return_value = False

            result = TaskRecovery.recover_from_tmux_failure(task, db_session)

            assert result is False
            assert task.status == TaskStatus.failed
            assert task.claude_status == ClaudeStatus.stopped
            assert "tmux session not found" in task.result

    def test_recover_from_tmux_failure_restart_success(self, db_session):
        """Test successful recovery by restarting Claude."""
        task = Task(title="Test Task", status=TaskStatus.running)
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        with patch("services.error_handler.TmuxService") as mock_tmux, \
             patch("services.context.get_context_file") as mock_context:
            mock_tmux.return_value.session_exists.return_value = True
            mock_context.return_value = "/tmp/context.txt"

            result = TaskRecovery.recover_from_tmux_failure(task, db_session)

            assert result is True
            assert task.claude_status == ClaudeStatus.starting
            assert task.claude_restarts > 0
            mock_tmux.return_value.restart_claude.assert_called_once()

    def test_recover_from_tmux_failure_restart_fails(self, db_session):
        """Test recovery failure when restart fails."""
        task = Task(title="Test Task", status=TaskStatus.running)
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        with patch("services.error_handler.TmuxService") as mock_tmux, \
             patch("services.context.get_context_file") as mock_context:
            mock_tmux.return_value.session_exists.return_value = True
            mock_tmux.return_value.restart_claude.side_effect = Exception("Restart failed")
            mock_context.return_value = "/tmp/context.txt"

            result = TaskRecovery.recover_from_tmux_failure(task, db_session)

            assert result is False
            assert task.status == TaskStatus.failed
            assert task.claude_status == ClaudeStatus.stopped
            assert "could not restart Claude" in task.result

    def test_detect_hanging_tasks(self, db_session):
        """Test detection of hanging tasks."""
        # Create some tasks
        task1 = Task(title="Running", status=TaskStatus.running)
        task2 = Task(title="Waiting", status=TaskStatus.waiting)
        task3 = Task(title="Completed", status=TaskStatus.completed)

        db_session.add_all([task1, task2, task3])
        db_session.commit()

        # Detect hanging tasks (for now, just checks they exist)
        hanging = TaskRecovery.detect_hanging_tasks(db_session)

        # The function returns empty list for now (just logs warnings)
        assert isinstance(hanging, list)

    def test_cleanup_orphaned_sessions(self, db_session):
        """Test cleanup of orphaned tmux sessions."""
        # Create a completed task (shouldn't have active session)
        task = Task(
            title="Completed Task",
            status=TaskStatus.completed,
            tmux_session="chorus-task-1",
        )
        db_session.add(task)
        db_session.commit()

        with patch("services.error_handler.TmuxService") as mock_tmux:
            # Simulate orphaned session exists in tmux
            mock_tmux.return_value.list_task_sessions.return_value = [1]

            cleaned = TaskRecovery.cleanup_orphaned_sessions(db_session)

            assert cleaned == 1
            mock_tmux.return_value.kill_task_session.assert_called_once_with(1)

    def test_cleanup_orphaned_sessions_handles_errors(self, db_session):
        """Test cleanup handles errors gracefully."""
        with patch("services.error_handler.TmuxService") as mock_tmux:
            # Simulate orphaned session that fails to kill
            mock_tmux.return_value.list_task_sessions.return_value = [1, 2]
            mock_tmux.return_value.kill_task_session.side_effect = [
                None,  # First succeeds
                Exception("Kill failed"),  # Second fails
            ]

            cleaned = TaskRecovery.cleanup_orphaned_sessions(db_session)

            # Should have cleaned 1 out of 2
            assert cleaned == 1
            assert mock_tmux.return_value.kill_task_session.call_count == 2

    def test_cleanup_no_orphaned_sessions(self, db_session):
        """Test cleanup when there are no orphaned sessions."""
        # Create a running task
        task = Task(
            title="Running Task",
            status=TaskStatus.running,
            tmux_session="chorus-task-1",
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        with patch("services.error_handler.TmuxService") as mock_tmux:
            # Same task in both DB and tmux - no orphans
            mock_tmux.return_value.list_task_sessions.return_value = [task.id]

            cleaned = TaskRecovery.cleanup_orphaned_sessions(db_session)

            assert cleaned == 0
            mock_tmux.return_value.kill_task_session.assert_not_called()
