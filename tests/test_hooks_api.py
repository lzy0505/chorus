"""Tests for Claude Code hooks API endpoints."""

import pytest
from sqlmodel import Session

from models import Task, TaskStatus, ClaudeStatus


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
        assert data["task_id"] == task_id

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
        assert response.json()["task_id"] == task_id


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
        assert data["task_id"] == task_id

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
        assert data["task_id"] == task_id

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
        assert data["task_id"] == task_id

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
