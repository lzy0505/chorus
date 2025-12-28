"""Database setup and session management."""

from sqlmodel import SQLModel, create_engine, Session

from config import DATABASE_URL

# Create engine
engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create database tables on startup."""
    SQLModel.metadata.create_all(engine)


def get_db():
    """FastAPI dependency for database sessions."""
    with Session(engine) as session:
        yield session
