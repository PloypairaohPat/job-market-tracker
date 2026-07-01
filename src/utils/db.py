"""Database engine and session management.

One engine per process; sessions are short-lived and created per unit
of work via `session_scope()`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.utils.config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def get_engine(database_url: str | None = None) -> Engine:
    """Return the process-wide engine, creating it on first use.

    Pass an explicit `database_url` to override (used by tests).
    """
    global _engine, _SessionFactory
    if _engine is None or database_url is not None:
        url = database_url or get_settings().database_url
        _engine = create_engine(url, pool_pre_ping=True, future=True)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Provide a transactional scope: commit on success, rollback on error."""
    get_engine(database_url)
    assert _SessionFactory is not None
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
