"""Database engine and session management.

One engine (and one connection pool) per distinct database URL per
process; sessions are short-lived and created per unit of work via
`session_scope()`.

Callers that pass an explicit URL (the daily runner, both ingesters,
the tests) get the cached engine for that URL on every call after the
first, instead of a fresh engine and pool each time. `None` always
means the URL from settings.
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

# url -> (engine, sessionmaker). The single source of truth.
_engines: dict[str, tuple[Engine, sessionmaker]] = {}

# The most recently resolved engine and session factory. Kept for
# backward compatibility only: nothing in this module reads them, so code
# (mostly test teardown) that resets them to None is harmless.
_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def _resolve(database_url: str | None) -> tuple[Engine, sessionmaker]:
    global _engine, _SessionFactory
    url = database_url or get_settings().database_url
    entry = _engines.get(url)
    if entry is None:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        entry = (engine, sessionmaker(bind=engine, expire_on_commit=False))
        _engines[url] = entry
    _engine, _SessionFactory = entry
    return entry


def get_engine(database_url: str | None = None) -> Engine:
    """Return the engine for `database_url`, creating it on first use.

    `None` means the URL from settings. The same URL always returns the
    same engine until `dispose_engines()` is called.
    """
    return _resolve(database_url)[0]


def dispose_engines() -> int:
    """Dispose every cached engine (closing its pooled connections) and
    forget it. Returns how many were disposed. For tests and for the end
    of a process."""
    global _engine, _SessionFactory
    n = len(_engines)
    for engine, _factory in _engines.values():
        engine.dispose()
    _engines.clear()
    _engine = None
    _SessionFactory = None
    return n


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Provide a transactional scope: commit on success, rollback on error."""
    _engine_for_url, factory = _resolve(database_url)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
