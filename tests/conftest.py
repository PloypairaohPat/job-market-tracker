"""Shared test fixtures and helpers."""

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from src.models import Base

_SAFE_TEST_HOSTS = frozenset({"localhost", "127.0.0.1"})


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when a destructive test helper is pointed at a non-test database."""


def assert_safe_test_url(url) -> None:
    """Refuse anything but a local database whose name contains "test".

    `reset_schema` drops the whole public schema, so a mistyped or
    leftover TEST_DATABASE_URL pointing at a real database would wipe
    it. The guard is deliberately narrow: local host AND a "test" name.
    """
    parsed = make_url(url)
    host = parsed.host or ""
    database = parsed.database or ""
    if host not in _SAFE_TEST_HOSTS:
        raise UnsafeTestDatabaseError(
            f"refusing to reset schema on host {host!r}: only localhost / 127.0.0.1 allowed"
        )
    if "test" not in database:
        raise UnsafeTestDatabaseError(
            f"refusing to reset schema on database {database!r}: name must contain 'test'"
        )


def reset_schema(engine: Engine) -> None:
    """Drop and recreate the public schema, then build current tables.

    More robust than `Base.metadata.drop_all`: it also removes tables
    this branch's metadata doesn't know about (e.g. tables created while
    testing another branch against the same database), which would
    otherwise block drops via foreign keys.

    Guarded by `assert_safe_test_url` -- refuses non-local or non-"test"
    databases before touching anything.
    """
    assert_safe_test_url(engine.url)
    with engine.begin() as conn:
        conn.execute(text("drop schema public cascade"))
        conn.execute(text("create schema public"))
    Base.metadata.create_all(engine)
