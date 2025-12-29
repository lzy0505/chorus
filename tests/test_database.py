"""Tests for database module."""

from sqlmodel import Session, select

from database import create_db_and_tables, get_db, engine
from models import Task, Document, DocumentReference


class TestDatabaseSetup:
    """Tests for database initialization."""

    def test_create_db_and_tables(self):
        """Test database tables are created."""
        # Should not raise any errors
        create_db_and_tables()

    def test_engine_exists(self):
        """Test database engine is configured."""
        assert engine is not None


class TestGetDbDependency:
    """Tests for FastAPI database dependency."""

    def test_get_db_yields_session(self):
        """Test get_db yields a valid session."""
        gen = get_db()
        session = next(gen)

        assert isinstance(session, Session)

        # Cleanup
        try:
            next(gen)
        except StopIteration:
            pass

    def test_get_db_session_is_usable(self):
        """Test yielded session can execute queries."""
        gen = get_db()
        session = next(gen)

        # Should be able to execute a simple query
        result = session.exec(select(Task)).all()
        assert isinstance(result, list)

        # Cleanup
        try:
            next(gen)
        except StopIteration:
            pass


class TestDatabaseOperations:
    """Tests for basic database operations."""

    def test_create_and_query_task(self, db: Session):
        """Test creating and querying a task."""
        task = Task(title="DB Test Task")
        db.add(task)
        db.commit()

        # Query it back
        result = db.exec(select(Task).where(Task.title == "DB Test Task")).first()
        assert result is not None
        assert result.title == "DB Test Task"

    def test_update_task(self, db: Session):
        """Test updating a task."""
        task = Task(title="Original Title")
        db.add(task)
        db.commit()
        db.refresh(task)

        task.title = "Updated Title"
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.title == "Updated Title"

    def test_delete_task(self, db: Session):
        """Test deleting a task."""
        task = Task(title="To Delete")
        db.add(task)
        db.commit()
        db.refresh(task)

        task_id = task.id
        db.delete(task)
        db.commit()

        result = db.get(Task, task_id)
        assert result is None

    def test_foreign_key_relationship(self, db: Session):
        """Test foreign key between DocumentReference and Document/Task."""
        doc = Document(path="fk_test.md")
        task = Task(title="FK Test Task")
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

        # Verify relationships
        assert ref.document_id == doc.id
        assert ref.task_id == task.id

    def test_unique_document_path(self, db: Session):
        """Test document path uniqueness constraint."""
        import pytest
        from sqlalchemy.exc import IntegrityError

        doc1 = Document(path="unique_test.md")
        db.add(doc1)
        db.commit()

        doc2 = Document(path="unique_test.md")
        db.add(doc2)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    def test_multiple_tasks(self, db: Session):
        """Test creating and querying multiple tasks."""
        tasks = [
            Task(title="Task 1", priority=1),
            Task(title="Task 2", priority=2),
            Task(title="Task 3", priority=3),
        ]
        for task in tasks:
            db.add(task)
        db.commit()

        result = db.exec(select(Task).order_by(Task.priority)).all()
        assert len(result) >= 3

        # Check ordering
        priorities = [t.priority for t in result if t.priority in [1, 2, 3]]
        assert priorities == sorted(priorities)
