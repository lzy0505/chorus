"""Tests for the context service."""

import pytest
from pathlib import Path
import tempfile
import shutil

from models import Task
from services.context import (
    get_context_dir,
    get_context_file,
    build_task_context,
    write_task_context,
    cleanup_task_context,
    context_exists,
    CONTEXT_BASE_DIR,
)


class TestGetContextPaths:
    """Tests for context path helpers."""

    def test_get_context_dir(self):
        """Test context directory path generation."""
        path = get_context_dir(42)
        assert path == CONTEXT_BASE_DIR / "task-42"

    def test_get_context_file(self):
        """Test context file path generation."""
        path = get_context_file(42)
        assert path == CONTEXT_BASE_DIR / "task-42" / "context.md"


class TestBuildTaskContext:
    """Tests for context building."""

    def test_basic_context(self):
        """Test basic context with just title."""
        task = Task(id=1, title="Fix login bug")
        context = build_task_context(task)

        assert "HIGHEST PRIORITY TASK" in context
        assert "# Current Task: Fix login bug" in context
        assert "Task ID: 1" in context

    def test_context_with_description(self):
        """Test context includes description."""
        task = Task(
            id=1,
            title="Fix login bug",
            description="Users cannot login after password reset",
        )
        context = build_task_context(task)

        assert "## Description" in context
        assert "Users cannot login after password reset" in context

    def test_context_without_gitbutler_info(self):
        """Test context excludes GitButler stack info (Chorus handles this)."""
        task = Task(
            id=1,
            title="Fix login bug",
            stack_name="task-1-fix-login-bug",
        )
        context = build_task_context(task)

        # GitButler info should NOT be in the context
        assert "GitButler Stack" not in context
        assert "## Git Workflow" not in context
        assert "but commit" not in context
        # But priority should be emphasized
        assert "HIGHEST PRIORITY TASK" in context

    def test_context_with_user_prompt(self):
        """Test context includes user-provided prompt."""
        task = Task(id=1, title="Fix login bug")
        context = build_task_context(task, user_prompt="Focus on the OAuth flow")

        assert "## Instructions" in context
        assert "Focus on the OAuth flow" in context

    def test_full_context(self):
        """Test full context with all fields."""
        task = Task(
            id=5,
            title="Add dark mode",
            description="Implement dark mode toggle in settings",
            stack_name="task-5-add-dark-mode",
        )
        context = build_task_context(task, user_prompt="Start with CSS variables")

        assert "HIGHEST PRIORITY TASK" in context
        assert "# Current Task: Add dark mode" in context
        assert "Task ID: 5" in context
        assert "Implement dark mode toggle in settings" in context
        assert "Start with CSS variables" in context
        # GitButler info should not be included
        assert "task-5-add-dark-mode" not in context


class TestWriteTaskContext:
    """Tests for writing context to files."""

    def setup_method(self):
        """Clean up any existing test context before each test."""
        self.test_task_id = 99999  # Use high ID to avoid conflicts
        cleanup_task_context(self.test_task_id)

    def teardown_method(self):
        """Clean up test context after each test."""
        cleanup_task_context(self.test_task_id)

    def test_write_creates_directory(self):
        """Test that write creates the context directory."""
        task = Task(id=self.test_task_id, title="Test task")
        context_file = write_task_context(task)

        assert context_file.parent.exists()
        assert context_file.parent == get_context_dir(self.test_task_id)

    def test_write_creates_file(self):
        """Test that write creates the context file."""
        task = Task(id=self.test_task_id, title="Test task")
        context_file = write_task_context(task)

        assert context_file.exists()
        assert context_file.name == "context.md"

    def test_write_content_correct(self):
        """Test that written content is correct."""
        task = Task(
            id=self.test_task_id,
            title="Test task",
            description="Test description",
        )
        context_file = write_task_context(task, user_prompt="Extra instructions")

        content = context_file.read_text()
        assert "# Current Task: Test task" in content
        assert "Test description" in content
        assert "Extra instructions" in content

    def test_write_overwrites_existing(self):
        """Test that write overwrites existing file."""
        task = Task(id=self.test_task_id, title="First title")
        write_task_context(task)

        task.title = "Second title"
        context_file = write_task_context(task)

        content = context_file.read_text()
        assert "Second title" in content
        assert "First title" not in content


class TestCleanupTaskContext:
    """Tests for context cleanup."""

    def test_cleanup_removes_directory(self):
        """Test that cleanup removes the context directory."""
        task_id = 99998
        task = Task(id=task_id, title="Test")
        write_task_context(task)

        assert get_context_dir(task_id).exists()

        cleanup_task_context(task_id)

        assert not get_context_dir(task_id).exists()

    def test_cleanup_nonexistent_is_safe(self):
        """Test that cleanup on non-existent directory is safe."""
        # Should not raise
        cleanup_task_context(99997)


class TestContextExists:
    """Tests for context existence check."""

    def setup_method(self):
        """Clean up test context."""
        self.test_task_id = 99996
        cleanup_task_context(self.test_task_id)

    def teardown_method(self):
        """Clean up test context."""
        cleanup_task_context(self.test_task_id)

    def test_exists_when_written(self):
        """Test that context_exists returns True when file exists."""
        task = Task(id=self.test_task_id, title="Test")
        write_task_context(task)

        assert context_exists(self.test_task_id) is True

    def test_not_exists_when_not_written(self):
        """Test that context_exists returns False when file doesn't exist."""
        assert context_exists(self.test_task_id) is False
