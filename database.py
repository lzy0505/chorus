"""Database setup and session management."""

from sqlmodel import SQLModel, create_engine, Session

from config import get_config

# Engine is created lazily on first access
_engine = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        _engine = create_engine(config.database.url, echo=False)
    return _engine


def create_db_and_tables():
    """Create database tables on startup."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_db():
    """FastAPI dependency for database sessions."""
    engine = get_engine()
    with Session(engine) as session:
        yield session
