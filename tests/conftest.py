"""Shared test fixtures and helpers."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.models import Base


def reset_schema(engine: Engine) -> None:
    """Drop and recreate the public schema, then build current tables.

    More robust than `Base.metadata.drop_all`: it also removes tables
    this branch's metadata doesn't know about (e.g. tables created while
    testing another branch against the same database), which would
    otherwise block drops via foreign keys.
    """
    with engine.begin() as conn:
        conn.execute(text("drop schema public cascade"))
        conn.execute(text("create schema public"))
    Base.metadata.create_all(engine)
