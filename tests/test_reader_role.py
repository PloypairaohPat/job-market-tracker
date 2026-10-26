"""The read-only Metabase role: every v_* view, no base table.

Roles are cluster-wide, so this uses a test-specific role name and drops
it afterwards.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from scripts.apply_views import apply_views
from src.dashboard.reader_role import ReaderRoleError, grant_reader
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
ROLE = "jmt_test_metabase_reader"
PASSWORD = "demo-only-not-secret"
BASE_TABLES = ("jobs", "lca_cases", "raw_responses", "ingestion_runs", "companies")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


def reader_url(role: str = ROLE, password: str = PASSWORD) -> str:
    return (
        make_url(TEST_DB_URL)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )


def drop_role(engine, role: str = ROLE) -> None:
    with engine.begin() as conn:
        if conn.execute(text("select 1 from pg_roles where rolname = :r"), {"r": role}).scalar():
            conn.execute(text(f'drop owned by "{role}"'))
            conn.execute(text(f'drop role "{role}"'))


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    drop_role(engine)
    yield engine
    drop_role(engine)
    engine.dispose()


def test_reader_reads_every_view_and_no_table(db):
    views = grant_reader(TEST_DB_URL, PASSWORD, role=ROLE)
    assert len(views) >= 7 and all(v.startswith("v_") for v in views)

    reader = create_engine(reader_url())
    try:
        with reader.connect() as conn:
            for view in views:
                conn.execute(text(f'select * from "{view}" limit 1')).all()
        for table in BASE_TABLES:
            with (
                reader.connect() as conn,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                conn.execute(text(f"select 1 from {table}"))
    finally:
        reader.dispose()

    with db.connect() as conn:
        table_grants = conn.execute(
            text(
                "select count(*) from information_schema.role_table_grants g "
                "join pg_tables t on t.tablename = g.table_name and t.schemaname = g.table_schema "
                "where g.grantee = :r"
            ),
            {"r": ROLE},
        ).scalar_one()
    assert table_grants == 0


def test_regrant_is_idempotent_and_picks_up_new_views(db):
    first = grant_reader(TEST_DB_URL, PASSWORD, role=ROLE)
    assert grant_reader(TEST_DB_URL, PASSWORD, role=ROLE) == first

    with db.begin() as conn:
        conn.execute(text("create view v_zz_new_metric as select 1 as n"))
        conn.execute(text("create view not_a_reader_view as select 1 as n"))
    views = grant_reader(TEST_DB_URL, PASSWORD, role=ROLE)
    assert "v_zz_new_metric" in views and "not_a_reader_view" not in views

    reader = create_engine(reader_url())
    try:
        with reader.connect() as conn:
            assert conn.execute(text("select n from v_zz_new_metric")).scalar_one() == 1
        with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("select n from not_a_reader_view"))
    finally:
        reader.dispose()


def test_regrant_revokes_a_stray_table_grant_and_updates_the_password(db):
    grant_reader(TEST_DB_URL, PASSWORD, role=ROLE)
    with db.begin() as conn:
        conn.execute(text(f'grant select on jobs to "{ROLE}"'))
    grant_reader(TEST_DB_URL, "demo-only-rotated", role=ROLE)

    reader = create_engine(reader_url(password="demo-only-rotated"))
    try:
        with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("select 1 from jobs"))
    finally:
        reader.dispose()


def test_refuses_empty_password_and_odd_role_names(db):
    with pytest.raises(ReaderRoleError, match="METABASE_READER_PASSWORD"):
        grant_reader(TEST_DB_URL, "", role=ROLE)
    with pytest.raises(ReaderRoleError, match="invalid role name"):
        grant_reader(TEST_DB_URL, PASSWORD, role='x"; drop table jobs; --')
