"""Tests for database models."""

from datetime import datetime, timezone

from sqlmodel import Session

from models import (
    Document,
    DocumentCategory,
    DocumentReference,
    Session as SessionModel,
    SessionStatus,
    Task,
    TaskStatus,
)


class TestSessionModel:
    """Tests for Session model."""

    def test_create_session(self, db: Session):
        """Test creating a session."""
        session = SessionModel(id="claude-test", status=SessionStatus.idle)
        db.add(session)
        db.commit()
        db.refresh(session)

        assert session.id == "claude-test"
        assert session.status == SessionStatus.idle
        assert session.task_id is None
        assert session.permission_prompt is None

    def test_session_status_values(self):
        """Test all session status values."""
        assert SessionStatus.idle == "idle"
        assert SessionStatus.busy == "busy"
        assert SessionStatus.waiting == "waiting"
        assert SessionStatus.stopped == "stopped"

    def test_session_with_output(self, db: Session):
        """Test session with last_output field."""
        session = SessionModel(
            id="claude-test",
            status=SessionStatus.busy,
            last_output="Processing task...",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        assert session.last_output == "Processing task..."


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
        assert task.status == TaskStatus.pending
        assert task.priority == 10

    def test_task_status_values(self):
        """Test all task status values."""
        assert TaskStatus.pending == "pending"
        assert TaskStatus.assigned == "assigned"
        assert TaskStatus.in_progress == "in_progress"
        assert TaskStatus.blocked == "blocked"
        assert TaskStatus.completed == "completed"
        assert TaskStatus.failed == "failed"

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


class TestDocumentReferenceModel:
    """Tests for DocumentReference model."""

    def test_create_reference(self, db: Session):
        """Test creating a document reference."""
        # Create document first
        doc = Document(path="test.md")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Create reference
        ref = DocumentReference(
            document_id=doc.id,
            start_line=10,
            end_line=20,
            note="Important section",
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        assert ref.id is not None
        assert ref.document_id == doc.id
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
