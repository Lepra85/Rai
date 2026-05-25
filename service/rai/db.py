"""SQLAlchemy engine, session, and Base shared by models + Alembic.

The engine is created lazily: importing this module must NOT require a live
DATABASE_URL (offline tooling and Alembic env need to import models without
opening a connection).
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from rai.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_SessionLocal = None


def get_engine():
    """Lazily create the engine on first use. Raises if DATABASE_URL is empty."""
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. Fill in service/.env before using the DB."
            )
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Yields a session and closes it on request end."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
