"""Tests for database models."""

from datetime import datetime, timezone

from sqlmodel import Session

from models import (
    ClaudeStatus,
    Document,
    DocumentCategory,
    DocumentReference,
    Task,
    TaskStatus,
)


class TestTaskModel:
    """Tests for Task model."""

    def test_create_task(self, db: Session):
        """Test creating a task."""
        task = Task(
            title="Test Task",
            description="A test task description",
            priority=10,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.id is not None
        assert task.title == "Test Task"
        assert task.description == "A test task description"
        assert task.status == TaskStatus.pending
        assert task.priority == 10

    def test_task_status_values(self):
        """Test all task status values."""
        assert TaskStatus.pending == "pending"
        assert TaskStatus.running == "running"
        assert TaskStatus.waiting == "waiting"
        assert TaskStatus.completed == "completed"
        assert TaskStatus.failed == "failed"

    def test_claude_status_values(self):
        """Test all Claude status values."""
        assert ClaudeStatus.stopped == "stopped"
        assert ClaudeStatus.starting == "starting"
        assert ClaudeStatus.idle == "idle"
        assert ClaudeStatus.busy == "busy"
        assert ClaudeStatus.waiting == "waiting"

    def test_task_default_values(self, db: Session):
        """Test task default values."""
        task = Task(title="Minimal Task")
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.description == ""
        assert task.priority == 0
        assert task.status == TaskStatus.pending
        assert task.branch_name is None
        assert task.tmux_session is None
        assert task.claude_status == ClaudeStatus.stopped
        assert task.claude_restarts == 0
        assert task.last_output == ""
        assert task.permission_prompt is None
        assert task.started_at is None
        assert task.completed_at is None
        assert task.commit_message is None
        assert task.result is None

    def test_task_with_timestamps(self, db: Session):
        """Test task with timestamp fields."""
        now = datetime.now(timezone.utc)
        task = Task(
            title="Timed Task",
            started_at=now,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # SQLite stores without timezone, so compare without tzinfo
        assert task.started_at is not None
        assert task.started_at.replace(tzinfo=None) == now.replace(tzinfo=None)
        assert task.completed_at is None

    def test_task_with_tmux_and_branch(self, db: Session):
        """Test task with tmux session and branch."""
        task = Task(
            title="Feature Task",
            branch_name="feat/auth",
            tmux_session="task-1",
            status=TaskStatus.running,
            claude_status=ClaudeStatus.busy,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.branch_name == "feat/auth"
        assert task.tmux_session == "task-1"
        assert task.status == TaskStatus.running
        assert task.claude_status == ClaudeStatus.busy

    def test_task_with_claude_restart(self, db: Session):
        """Test task tracking Claude restarts."""
        task = Task(
            title="Unstable Task",
            claude_restarts=3,
            last_output="> Working on feature...",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.claude_restarts == 3
        assert task.last_output == "> Working on feature..."

    def test_task_waiting_for_permission(self, db: Session):
        """Test task in waiting state with permission prompt."""
        task = Task(
            title="Permission Task",
            status=TaskStatus.waiting,
            claude_status=ClaudeStatus.waiting,
            permission_prompt="Allow write to file.py? (y/n)",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.status == TaskStatus.waiting
        assert task.claude_status == ClaudeStatus.waiting
        assert task.permission_prompt == "Allow write to file.py? (y/n)"

    def test_task_completed(self, db: Session):
        """Test completed task with result."""
        now = datetime.now(timezone.utc)
        task = Task(
            title="Done Task",
            status=TaskStatus.completed,
            completed_at=now,
            commit_message="feat: implement auth system",
            result="Successfully implemented OAuth2 authentication",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.status == TaskStatus.completed
        assert task.completed_at is not None
        assert task.commit_message == "feat: implement auth system"
        assert task.result == "Successfully implemented OAuth2 authentication"

    def test_task_failed(self, db: Session):
        """Test failed task with error result."""
        task = Task(
            title="Failed Task",
            status=TaskStatus.failed,
            result="Claude crashed with OOM error",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.status == TaskStatus.failed
        assert task.result == "Claude crashed with OOM error"


class TestDocumentModel:
    """Tests for Document model."""

    def test_create_document(self, db: Session):
        """Test creating a document."""
        doc = Document(
            path="docs/readme.md",
            category=DocumentCategory.instructions,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert doc.id is not None
        assert doc.path == "docs/readme.md"
        assert doc.category == DocumentCategory.instructions
        assert doc.pinned is False

    def test_document_categories(self):
        """Test all document category values."""
        assert DocumentCategory.instructions == "instructions"
        assert DocumentCategory.plans == "plans"
        assert DocumentCategory.communication == "communication"
        assert DocumentCategory.context == "context"
        assert DocumentCategory.general == "general"

    def test_pinned_document(self, db: Session):
        """Test pinned document."""
        doc = Document(
            path="CLAUDE.md",
            category=DocumentCategory.instructions,
            pinned=True,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert doc.pinned is True

    def test_document_with_description(self, db: Session):
        """Test document with description."""
        doc = Document(
            path="PLAN.md",
            category=DocumentCategory.plans,
            description="Implementation roadmap",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert doc.description == "Implementation roadmap"

    def test_document_default_category(self, db: Session):
        """Test document defaults to general category."""
        doc = Document(path="random.md")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert doc.category == DocumentCategory.general


class TestDocumentReferenceModel:
    """Tests for DocumentReference model."""

    def test_create_reference(self, db: Session):
        """Test creating a document reference."""
        # Create document and task first
        doc = Document(path="test.md")
        task = Task(title="Ref Task")
        db.add(doc)
        db.add(task)
        db.commit()
        db.refresh(doc)
        db.refresh(task)

        # Create reference
        ref = DocumentReference(
            document_id=doc.id,
            task_id=task.id,
            start_line=10,
            end_line=20,
            note="Important section",
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        assert ref.id is not None
        assert ref.document_id == doc.id
        assert ref.task_id == task.id
        assert ref.start_line == 10
        assert ref.end_line == 20
        assert ref.note == "Important section"

    def test_reference_with_task(self, db: Session):
        """Test reference linked to a task."""
        doc = Document(path="spec.md")
        task = Task(title="Implement feature")
        db.add(doc)
        db.add(task)
        db.commit()
        db.refresh(doc)
        db.refresh(task)

        ref = DocumentReference(
            document_id=doc.id,
            task_id=task.id,
            start_line=1,
            end_line=50,
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        assert ref.task_id == task.id

    def test_reference_without_note(self, db: Session):
        """Test reference without optional note."""
        doc = Document(path="code.md")
        task = Task(title="Code task")
        db.add(doc)
        db.add(task)
        db.commit()
        db.refresh(doc)
        db.refresh(task)

        ref = DocumentReference(
            document_id=doc.id,
            task_id=task.id,
            start_line=1,
            end_line=10,
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        assert ref.note is None
