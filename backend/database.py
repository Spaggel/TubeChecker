import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/db.sqlite3"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables and apply lightweight column migrations for existing DBs."""
    # Import here to avoid circular imports (models imports Base from this module)
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS, so guard with
    # a pragma check and swallow the error if the column already exists.
    _ensure_column("videos", "error", "TEXT")


def _ensure_column(table: str, column: str, col_type: str) -> None:
    """Add *column* to *table* if it does not already exist (SQLite only)."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}  # column name is index 1
        if column not in existing:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info("Migration: added column %s.%s", table, column)
            except Exception as exc:  # pragma: no cover
                logger.warning("Migration skipped (%s.%s): %s", table, column, exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
