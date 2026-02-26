"""
PharmaPulse Database Configuration

Sets up the SQLAlchemy engine, session factory, and declarative base.
Uses SQLite locally with a file-based database (pharmapulse.db).

Architecture:
    - SQLAlchemy 2.0 style with mapped_column and type annotations
    - SQLite for local development; change DATABASE_URL only to switch to PostgreSQL
    - All models inherit from Base (defined here)
    - Session management via get_db() dependency for FastAPI

Key Design Decisions:
    - check_same_thread=False for SQLite to allow multi-threaded access from FastAPI
    - pool_pre_ping=True to handle stale connections gracefully
    - echo=False in production; set SQLALCHEMY_ECHO=true for SQL debugging
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Database file location: backend/pharmapulse.db
# This ensures the DB is created relative to the backend directory
_DB_DIR = Path(__file__).parent
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{_DB_DIR / 'pharmapulse.db'}"
)

# Create SQLAlchemy engine
# - check_same_thread=False: required for SQLite with FastAPI (multi-threaded)
# - pool_pre_ping=True: verify connections before using them
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True,
    echo=os.environ.get("SQLALCHEMY_ECHO", "false").lower() == "true",
)


# Enable WAL mode and foreign keys for SQLite for better concurrency
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key support and WAL mode for SQLite connections."""
    if "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Session factory — each request gets its own session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    Declarative base class for all SQLAlchemy ORM models.
    All PharmaPulse tables inherit from this base.
    """
    pass


def get_db():
    """
    FastAPI dependency that provides a database session.
    Yields a session and ensures it's closed after the request.

    Usage in FastAPI endpoints:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Create all database tables from ORM model definitions.
    Called during application startup and by seed_data.py.

    Note: import models before calling this to ensure all tables
    are registered with Base.metadata.
    """
    from . import models  # noqa: F401 — side-effect import to register models
    Base.metadata.create_all(bind=engine)


