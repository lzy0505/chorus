"""Tests for Claude Code hooks API endpoints."""

import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import Session

from models import Task, TaskStatus, ClaudeStatus
from services.gitbutler import Commit, GitButlerError


class TestHookSessionStart:
    """Tests for POST /api/hooks/sessionstart endpoint."""

    def test_maps_session_to_running_task(self, client, engine):
        """Test that session is mapped to a running task."""
        # Create a running task
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                tmux_session="task-1",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # Send SessionStart event
        response = client.post(
            "/api/hooks/sessionstart",
            json={
                "session_id": "test-session-123",
                "hook_event_name": "SessionStart",
                "cwd": "/path/to/project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)

        # Verify task was updated
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_session_id == "test-session-123"
            assert task.claude_status == ClaudeStatus.idle

    def test_ignores_when_no_running_task(self, client):
        """Test that event is ignored when no running task exists."""
        response = client.post(
            "/api/hooks/sessionstart",
            json={
                "session_id": "orphan-session",
                "hook_event_name": "SessionStart",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["task_id"] is None

    def test_maps_to_waiting_task(self, client, engine):
        """Test that session can be mapped to a waiting task."""
        with Session(engine) as db:
            task = Task(
                title="Waiting Task",
                status=TaskStatus.waiting,
                tmux_session="task-2",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/sessionstart",
            json={
                "session_id": "waiting-session",
                "hook_event_name": "SessionStart",
            },
        )

        assert response.status_code == 200
        assert response.json()["task_id"] == str(task_id)


class TestHookStop:
    """Tests for POST /api/hooks/stop endpoint."""

    def test_sets_claude_status_to_idle(self, client, engine):
        """Test that Stop event sets Claude status to idle."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-456",
                claude_status=ClaudeStatus.busy,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/stop",
            json={
                "session_id": "session-456",
                "hook_event_name": "Stop",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.idle

    def test_resets_waiting_task_to_running(self, client, engine):
        """Test that Stop event resets waiting task to running."""
        with Session(engine) as db:
            task = Task(
                title="Waiting Task",
                status=TaskStatus.waiting,
                claude_session_id="session-789",
                claude_status=ClaudeStatus.waiting,
                permission_prompt="Allow file write?",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/stop",
            json={
                "session_id": "session-789",
                "hook_event_name": "Stop",
            },
        )

        assert response.status_code == 200

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.running
            assert task.claude_status == ClaudeStatus.idle
            assert task.permission_prompt is None

    def test_ignores_unknown_session(self, client):
        """Test that unknown session is ignored."""
        response = client.post(
            "/api/hooks/stop",
            json={
                "session_id": "unknown-session",
                "hook_event_name": "Stop",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestHookPermissionRequest:
    """Tests for POST /api/hooks/permissionrequest endpoint."""

    def test_sets_task_to_waiting(self, client, engine):
        """Test that PermissionRequest sets task status to waiting."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-perm",
                claude_status=ClaudeStatus.busy,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/permissionrequest",
            json={
                "session_id": "session-perm",
                "hook_event_name": "PermissionRequest",
                "transcript_path": "/path/to/transcript.jsonl",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.waiting
            assert task.claude_status == ClaudeStatus.waiting
            assert task.permission_prompt is not None

    def test_ignores_unknown_session(self, client):
        """Test that unknown session is ignored."""
        response = client.post(
            "/api/hooks/permissionrequest",
            json={
                "session_id": "unknown",
                "hook_event_name": "PermissionRequest",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestHookSessionEnd:
    """Tests for POST /api/hooks/sessionend endpoint."""

    def test_clears_session_and_sets_stopped(self, client, engine):
        """Test that SessionEnd clears session and sets status to stopped."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-end",
                claude_status=ClaudeStatus.idle,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/sessionend",
            json={
                "session_id": "session-end",
                "hook_event_name": "SessionEnd",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_session_id is None
            assert task.claude_status == ClaudeStatus.stopped

    def test_ignores_unknown_session(self, client):
        """Test that unknown session is ignored."""
        response = client.post(
            "/api/hooks/sessionend",
            json={
                "session_id": "unknown",
                "hook_event_name": "SessionEnd",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestHookNotification:
    """Tests for POST /api/hooks/notification endpoint."""

    def test_sets_idle_status(self, client, engine):
        """Test that Notification sets Claude status to idle."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-notif",
                claude_status=ClaudeStatus.busy,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/notification",
            json={
                "session_id": "session-notif",
                "hook_event_name": "Notification",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_status == ClaudeStatus.idle

    def test_preserves_waiting_status(self, client, engine):
        """Test that Notification doesn't change waiting status."""
        with Session(engine) as db:
            task = Task(
                title="Waiting Task",
                status=TaskStatus.waiting,
                claude_session_id="session-wait-notif",
                claude_status=ClaudeStatus.waiting,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/notification",
            json={
                "session_id": "session-wait-notif",
                "hook_event_name": "Notification",
            },
        )

        assert response.status_code == 200

        with Session(engine) as db:
            task = db.get(Task, task_id)
            # Should remain waiting, not change to idle
            assert task.claude_status == ClaudeStatus.waiting

    def test_ignores_unknown_session(self, client):
        """Test that unknown session is ignored."""
        response = client.post(
            "/api/hooks/notification",
            json={
                "session_id": "unknown",
                "hook_event_name": "Notification",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestHookPayloadValidation:
    """Tests for hook payload validation."""

    def test_missing_session_id(self, client):
        """Test handling of missing session_id."""
        response = client.post(
            "/api/hooks/stop",
            json={
                "hook_event_name": "Stop",
            },
        )

        # Pydantic should reject this
        assert response.status_code == 422

    def test_extra_fields_allowed(self, client, engine):
        """Test that extra fields in payload are allowed."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-extra",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/stop",
            json={
                "session_id": "session-extra",
                "hook_event_name": "Stop",
                "extra_field": "ignored",
                "another_field": 123,
            },
        )

        # Should still work
        assert response.status_code == 200


class TestHookEndpointRouting:
    """Tests for hook endpoint routing."""

    def test_all_endpoints_exist(self, client):
        """Test that all hook endpoints are registered."""
        endpoints = [
            "/api/hooks/sessionstart",
            "/api/hooks/stop",
            "/api/hooks/permissionrequest",
            "/api/hooks/sessionend",
            "/api/hooks/notification",
            "/api/hooks/posttooluse",
        ]

        for endpoint in endpoints:
            response = client.post(
                endpoint,
                json={
                    "session_id": "test",
                    "hook_event_name": "Test",
                },
            )
            # Should not return 404
            assert response.status_code != 404, f"Endpoint {endpoint} not found"

    def test_case_insensitive_event_names(self, client, engine):
        """Test that different case event names work."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-case",
            )
            db.add(task)
            db.commit()

        # The endpoint URL is lowercase, but hook_event_name can vary
        response = client.post(
            "/api/hooks/stop",
            json={
                "session_id": "session-case",
                "hook_event_name": "STOP",  # uppercase
            },
        )

        assert response.status_code == 200


class TestHookPostToolUse:
    """Tests for POST /api/hooks/posttooluse endpoint."""

    @patch("api.hooks.GitButlerService")
    def test_commits_on_file_edit(self, mock_gb_class, client, engine):
        """Test that file edit triggers commit to task's stack."""
        # Setup mock
        mock_commit = Commit(
            cli_id="c1",
            commit_id="abc123def456",
            message="Auto commit",
            author_name="User",
            author_email="user@test.com",
            created_at="2025-01-01T00:00:00Z",
        )
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = mock_commit
        mock_gb_class.return_value = mock_service

        # Create task with stack
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-edit",
                stack_name="task-1-feature",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-edit",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)
        assert "abc123de" in data["message"]  # Commit ID prefix

        # Verify GitButler was called
        mock_service.commit_to_stack.assert_called_once_with("task-1-feature")

    @patch("api.hooks.GitButlerService")
    def test_commits_on_write_tool(self, mock_gb_class, client, engine):
        """Test that Write tool triggers commit."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = Commit(
            cli_id="c1", commit_id="xyz789", message="", author_name="",
            author_email="", created_at=""
        )
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-write",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-write",
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_service.commit_to_stack.assert_called_once()

    def test_skips_non_file_edit_tools(self, client, engine):
        """Test that non-file-editing tools are skipped."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-bash",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-bash",
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert "not a file-editing tool" in data["message"]

    def test_skips_read_tool(self, client, engine):
        """Test that Read tool is skipped."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-read",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-read",
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "skipped"

    def test_ignores_unknown_session(self, client):
        """Test that unknown session is ignored."""
        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "unknown-session",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_ignores_task_without_stack(self, client, engine):
        """Test that task without stack is ignored."""
        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-no-stack",
                stack_name=None,  # No stack assigned
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-no-stack",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["task_id"] == str(task_id)
        assert "no GitButler stack" in data["message"]

    @patch("api.hooks.GitButlerService")
    def test_handles_nothing_to_commit(self, mock_gb_class, client, engine):
        """Test handling when there are no changes to commit."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = None  # No commit
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-empty",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-empty",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["task_id"] == str(task_id)
        assert "No changes to commit" in data["message"]

    @patch("api.hooks.GitButlerService")
    def test_handles_gitbutler_error(self, mock_gb_class, client, engine):
        """Test handling of GitButler errors."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.side_effect = GitButlerError("Stack not found")
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-error",
                stack_name="missing-stack",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-error",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["task_id"] == str(task_id)
        assert "GitButler error" in data["message"]

    @patch("api.hooks.GitButlerService")
    def test_commits_without_tool_name(self, mock_gb_class, client, engine):
        """Test that missing tool_name still triggers commit."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = Commit(
            cli_id="c1", commit_id="abc123", message="", author_name="",
            author_email="", created_at=""
        )
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-no-tool",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-no-tool",
                "hook_event_name": "PostToolUse",
                # No tool_name provided
            },
        )

        assert response.status_code == 200
        # Without tool_name, we commit (conservative approach)
        assert response.json()["status"] == "ok"

    @patch("api.hooks.GitButlerService")
    def test_commits_on_multi_edit(self, mock_gb_class, client, engine):
        """Test that MultiEdit tool triggers commit."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = Commit(
            cli_id="c1", commit_id="multi123", message="", author_name="",
            author_email="", created_at=""
        )
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-multi",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-multi",
                "hook_event_name": "PostToolUse",
                "tool_name": "MultiEdit",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @patch("api.hooks.GitButlerService")
    def test_commits_on_notebook_edit(self, mock_gb_class, client, engine):
        """Test that NotebookEdit tool triggers commit."""
        mock_service = MagicMock()
        mock_service.commit_to_stack.return_value = Commit(
            cli_id="c1", commit_id="nb123", message="", author_name="",
            author_email="", created_at=""
        )
        mock_gb_class.return_value = mock_service

        with Session(engine) as db:
            task = Task(
                title="Test Task",
                status=TaskStatus.running,
                claude_session_id="session-notebook",
                stack_name="my-stack",
            )
            db.add(task)
            db.commit()

        response = client.post(
            "/api/hooks/posttooluse",
            json={
                "session_id": "session-notebook",
                "hook_event_name": "PostToolUse",
                "tool_name": "NotebookEdit",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
