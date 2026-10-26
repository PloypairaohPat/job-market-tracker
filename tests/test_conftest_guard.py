"""Unit tests for the reset_schema safety guard (no database needed)."""

import pytest
from sqlalchemy import create_engine

from tests.conftest import UnsafeTestDatabaseError, assert_safe_test_url, reset_schema


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/jobmarket_test",
        "postgresql+psycopg2://postgres:postgres@localhost:55440/test_db",
        "postgresql://u:p@localhost/my_testing",
    ],
)
def test_guard_accepts_local_test_databases(url):
    assert_safe_test_url(url)


@pytest.mark.parametrize(
    "url",
    [
        # name lacks "test"
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/jobmarket",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres",
        # remote host, even with a test name
        "postgresql+psycopg2://postgres:postgres@db.example.com:5432/jobmarket_test",
        "postgresql+psycopg2://postgres:postgres@10.0.0.5:5432/jobmarket_test",
        # no host at all (unix socket) is not on the allowlist
        "postgresql+psycopg2://postgres@/jobmarket_test",
    ],
)
def test_guard_refuses_unsafe_urls(url):
    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_url(url)


def test_reset_schema_refuses_before_connecting():
    # create_engine is lazy: if the guard didn't fire first, this would try
    # to connect to a database that doesn't exist and fail differently.
    engine = create_engine("postgresql+psycopg2://postgres:postgres@127.0.0.1:1/jobmarket")
    with pytest.raises(UnsafeTestDatabaseError):
        reset_schema(engine)
