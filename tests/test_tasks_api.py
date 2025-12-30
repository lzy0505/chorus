"""Tests for Task API endpoints."""

import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import Session

from models import Task, TaskStatus, ClaudeStatus
from services.tmux import SessionExistsError, SessionNotFoundError
from services.gitbutler import Stack, StackExistsError, GitButlerError


class TestTaskCRUD:
    """Tests for Task CRUD endpoints."""

    def test_create_task(self, client):
        """Test creating a task."""
        response = client.post(
            "/api/tasks",
            json={
                "title": "Implement auth",
                "description": "Add user authentication",
                "priority": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Implement auth"
        assert data["description"] == "Add user authentication"
        assert data["priority"] == 5
        assert data["status"] == "pending"
        assert data["claude_status"] == "stopped"

    def test_create_task_minimal(self, client):
        """Test creating a task with only required fields."""
        response = client.post(
            "/api/tasks",
            json={"title": "Quick fix"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Quick fix"
        assert data["description"] == ""
        assert data["priority"] == 0

    def test_list_tasks(self, client, engine):
        """Test listing all tasks."""
        with Session(engine) as db:
            db.add(Task(title="Task 1", priority=1))
            db.add(Task(title="Task 2", priority=5))
            db.add(Task(title="Task 3", priority=3))
            db.commit()

        response = client.get("/api/tasks")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should be ordered by priority desc
        assert data[0]["title"] == "Task 2"
        assert data[1]["title"] == "Task 3"
        assert data[2]["title"] == "Task 1"

    def test_list_tasks_filter_by_status(self, client, engine):
        """Test filtering tasks by status."""
        with Session(engine) as db:
            db.add(Task(title="Pending", status=TaskStatus.pending))
            db.add(Task(title="Running", status=TaskStatus.running))
            db.add(Task(title="Completed", status=TaskStatus.completed))
            db.commit()

        response = client.get("/api/tasks?status=running")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Running"

    def test_get_task(self, client, engine):
        """Test getting a task by ID."""
        with Session(engine) as db:
            task = Task(title="Test Task")
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.get(f"/api/tasks/{task_id}")

        assert response.status_code == 200
        assert response.json()["title"] == "Test Task"

    def test_get_task_not_found(self, client):
        """Test getting non-existent task."""
        response = client.get("/api/tasks/999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_update_task(self, client, engine):
        """Test updating a task."""
        with Session(engine) as db:
            task = Task(title="Old Title", description="Old desc", priority=1)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.put(
            f"/api/tasks/{task_id}",
            json={
                "title": "New Title",
                "priority": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title"
        assert data["description"] == "Old desc"  # Unchanged
        assert data["priority"] == 10

    def test_delete_task_pending(self, client, engine):
        """Test deleting a pending task."""
        with Session(engine) as db:
            task = Task(title="To Delete", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify deleted
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 404

    def test_delete_task_failed(self, client, engine):
        """Test deleting a failed task."""
        with Session(engine) as db:
            task = Task(title="Failed", status=TaskStatus.failed)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 200

    def test_delete_task_running_fails(self, client, engine):
        """Test that deleting a running task fails."""
        with Session(engine) as db:
            task = Task(title="Running", status=TaskStatus.running)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.delete(f"/api/tasks/{task_id}")

        assert response.status_code == 400
        assert "Cannot delete running task" in response.json()["detail"]


class TestTaskStart:
    """Tests for POST /api/tasks/{id}/start endpoint."""

    @patch("api.tasks.HooksService")
    @patch("api.tasks.TmuxService")
    @patch("api.tasks.GitButlerService")
    def test_start_task_success(
        self, mock_gb_class, mock_tmux_class, mock_hooks_class, client, engine
    ):
        """Test starting a pending task."""
        # Setup mocks
        mock_gb = MagicMock()
        mock_gb.create_stack.return_value = Stack(
            name="task-1-test", cli_id="t1", commits=[], changes=[]
        )
        mock_gb_class.return_value = mock_gb

        mock_tmux = MagicMock()
        mock_tmux.create_task_session.return_value = "claude-task-1"
        mock_tmux.get_session_id.return_value = "claude-task-1"
        mock_tmux_class.return_value = mock_tmux

        mock_hooks = MagicMock()
        mock_hooks_class.return_value = mock_hooks

        with Session(engine) as db:
            task = Task(title="Test Task", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/start")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "started" in data["message"]

        # Verify services were called
        mock_gb.create_stack.assert_called_once()
        mock_tmux.create_task_session.assert_called_once_with(task_id)
        mock_hooks.ensure_hooks.assert_called_once()
        mock_tmux.start_claude.assert_called_once()

        # Verify task was updated
        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.running
            assert task.stack_name == "task-1-test"
            assert task.tmux_session == "claude-task-1"
            assert task.started_at is not None

    @patch("api.tasks.HooksService")
    @patch("api.tasks.TmuxService")
    @patch("api.tasks.GitButlerService")
    def test_start_task_with_initial_prompt(
        self, mock_gb_class, mock_tmux_class, mock_hooks_class, client, engine
    ):
        """Test starting a task with an initial prompt."""
        mock_gb = MagicMock()
        mock_gb.create_stack.return_value = Stack(
            name="task-1-test", cli_id="t1", commits=[], changes=[]
        )
        mock_gb_class.return_value = mock_gb

        mock_tmux = MagicMock()
        mock_tmux.create_task_session.return_value = "claude-task-1"
        mock_tmux_class.return_value = mock_tmux

        mock_hooks = MagicMock()
        mock_hooks_class.return_value = mock_hooks

        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/start",
            json={"initial_prompt": "Fix the login bug"},
        )

        assert response.status_code == 200
        # Context is now written to file and passed via context_file parameter
        from pathlib import Path
        mock_tmux.start_claude.assert_called_once_with(
            task_id, context_file=Path(f"/tmp/chorus/task-{task_id}/context.md")
        )

    def test_start_task_not_pending(self, client, engine):
        """Test that starting a non-pending task fails."""
        with Session(engine) as db:
            task = Task(title="Running", status=TaskStatus.running)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/start")

        assert response.status_code == 400
        assert "running" in response.json()["detail"]

    @patch("api.tasks.GitButlerService")
    def test_start_task_gitbutler_error(self, mock_gb_class, client, engine):
        """Test handling GitButler errors on start."""
        mock_gb = MagicMock()
        mock_gb.create_stack.side_effect = GitButlerError("Failed to create stack")
        mock_gb_class.return_value = mock_gb

        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/start")

        assert response.status_code == 500
        assert "GitButler error" in response.json()["detail"]


class TestTaskRestartClaude:
    """Tests for POST /api/tasks/{id}/restart-claude endpoint."""

    @patch("api.tasks.TmuxService")
    def test_restart_claude_success(self, mock_tmux_class, client, engine):
        """Test restarting Claude."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_session_id="old-session",
                claude_restarts=2,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/restart-claude")

        assert response.status_code == 200
        data = response.json()
        assert "restart #3" in data["message"]

        # Context file path is passed to restart_claude
        from pathlib import Path
        mock_tmux.restart_claude.assert_called_once_with(
            task_id, context_file=Path(f"/tmp/chorus/task-{task_id}/context.md")
        )

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.claude_restarts == 3
            assert task.claude_session_id is None
            assert task.claude_status == ClaudeStatus.starting

    @patch("api.tasks.TmuxService")
    def test_restart_claude_from_waiting(self, mock_tmux_class, client, engine):
        """Test restarting Claude when task is waiting."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.waiting,
                permission_prompt="Allow?",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/restart-claude")

        assert response.status_code == 200

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.running
            assert task.permission_prompt is None

    def test_restart_claude_not_running(self, client, engine):
        """Test that restarting a non-running task fails."""
        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/restart-claude")

        assert response.status_code == 400


class TestTaskSend:
    """Tests for POST /api/tasks/{id}/send endpoint."""

    @patch("api.tasks.TmuxService")
    def test_send_message_success(self, mock_tmux_class, client, engine):
        """Test sending a message to Claude."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.idle,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/send",
            json={"message": "Fix the bug"},
        )

        assert response.status_code == 200
        mock_tmux.send_keys.assert_called_once_with(task_id, "Fix the bug")

    def test_send_message_claude_busy(self, client, engine):
        """Test that sending when Claude is busy fails."""
        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                claude_status=ClaudeStatus.busy,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/send",
            json={"message": "Hello"},
        )

        assert response.status_code == 400
        assert "busy" in response.json()["detail"]


class TestTaskRespond:
    """Tests for POST /api/tasks/{id}/respond endpoint."""

    @patch("api.tasks.TmuxService")
    def test_respond_approve(self, mock_tmux_class, client, engine):
        """Test approving a permission prompt."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.waiting,
                permission_prompt="Allow file write?",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/respond",
            json={"confirm": True},
        )

        assert response.status_code == 200
        assert "approved" in response.json()["message"]
        mock_tmux.send_confirmation.assert_called_once_with(task_id, True)

    @patch("api.tasks.TmuxService")
    def test_respond_deny(self, mock_tmux_class, client, engine):
        """Test denying a permission prompt."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.waiting)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/respond",
            json={"confirm": False},
        )

        assert response.status_code == 200
        assert "denied" in response.json()["message"]

    def test_respond_not_waiting(self, client, engine):
        """Test that responding when not waiting fails."""
        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.running)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/respond",
            json={"confirm": True},
        )

        assert response.status_code == 400


class TestTaskComplete:
    """Tests for POST /api/tasks/{id}/complete endpoint."""

    @patch("api.tasks.TmuxService")
    def test_complete_task_success(
        self, mock_tmux_class, client, engine
    ):
        """Test completing a running task."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                stack_name="task-1-test",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/complete",
            json={"result": "All tests passing"},
        )

        assert response.status_code == 200

        mock_tmux.kill_task_session.assert_called_once_with(task_id)

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.completed
            assert task.result == "All tests passing"
            assert task.completed_at is not None
            # Stack is preserved
            assert task.stack_name == "task-1-test"

    def test_complete_task_not_running(self, client, engine):
        """Test that completing a non-running task fails."""
        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.pending)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(f"/api/tasks/{task_id}/complete")

        assert response.status_code == 400


class TestTaskFail:
    """Tests for POST /api/tasks/{id}/fail endpoint."""

    @patch("api.tasks.GitButlerService")
    @patch("api.tasks.HooksService")
    @patch("api.tasks.TmuxService")
    def test_fail_task_success(
        self, mock_tmux_class, mock_hooks_class, mock_gb_class, client, engine
    ):
        """Test failing a running task."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        mock_hooks = MagicMock()
        mock_hooks_class.return_value = mock_hooks

        mock_gb = MagicMock()
        mock_gb_class.return_value = mock_gb

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                stack_name="task-1-test",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/fail",
            json={"reason": "Tests failing", "delete_stack": False},
        )

        assert response.status_code == 200

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == TaskStatus.failed
            assert task.result == "Tests failing"
            # Stack preserved when delete_stack=False
            assert task.stack_name == "task-1-test"

    @patch("api.tasks.GitButlerService")
    @patch("api.tasks.HooksService")
    @patch("api.tasks.TmuxService")
    def test_fail_task_delete_stack(
        self, mock_tmux_class, mock_hooks_class, mock_gb_class, client, engine
    ):
        """Test failing a task and deleting its stack."""
        mock_tmux = MagicMock()
        mock_tmux_class.return_value = mock_tmux

        mock_hooks = MagicMock()
        mock_hooks_class.return_value = mock_hooks

        mock_gb = MagicMock()
        mock_gb_class.return_value = mock_gb

        with Session(engine) as db:
            task = Task(
                title="Test",
                status=TaskStatus.running,
                stack_name="task-1-test",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.post(
            f"/api/tasks/{task_id}/fail",
            json={"delete_stack": True},
        )

        assert response.status_code == 200
        mock_gb.delete_stack.assert_called_once_with("task-1-test")

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.stack_name is None


class TestTaskOutput:
    """Tests for GET /api/tasks/{id}/output endpoint."""

    @patch("api.tasks.TmuxService")
    def test_get_output_success(self, mock_tmux_class, client, engine):
        """Test getting task output."""
        mock_tmux = MagicMock()
        mock_tmux.capture_output.return_value = "Claude output here..."
        mock_tmux_class.return_value = mock_tmux

        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.running)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.get(f"/api/tasks/{task_id}/output?lines=50")

        assert response.status_code == 200
        data = response.json()
        assert data["output"] == "Claude output here..."
        assert data["lines"] == 50
        mock_tmux.capture_output.assert_called_once_with(task_id, lines=50)

    def test_get_output_not_running(self, client, engine):
        """Test that getting output from non-running task fails."""
        with Session(engine) as db:
            task = Task(title="Test", status=TaskStatus.completed)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        response = client.get(f"/api/tasks/{task_id}/output")

        assert response.status_code == 400
