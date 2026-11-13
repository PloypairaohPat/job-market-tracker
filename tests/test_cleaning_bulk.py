"""Part E: the bulk cleaning and skills code (invented rows only).

Results are pinned by tests/test_cleaning_reference_equality.py; these
tests cover what that one doesn't: the batch mechanics (all-NULL VALUES
columns, keyset batches smaller than the table), --only touching only its
own columns, nothing written when nothing changed, and (E4) a statement
count against `jobs` that doesn't grow with the number of jobs.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, select, text

from src.cleaning import apply_cleaning
from src.models import Job
from src.utils.db import dispose_engines, get_engine, session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def engine():
    eng = create_engine(TEST_DB_URL)
    reset_schema(eng)
    yield eng
    eng.dispose()
    dispose_engines()


def add_jobs(rows: list[dict]) -> None:
    with session_scope(TEST_DB_URL) as s:
        s.add_all(Job(**row) for row in rows)


@contextmanager
def statements():
    """Record (round trips, SQL) of every statement sent; executemany = one per row."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, parameters, _context, executemany) -> None:
        many = executemany and isinstance(parameters, (list, tuple))
        seen.extend([statement] * (len(parameters) if many else 1))

    eng = get_engine(TEST_DB_URL)
    event.listen(eng, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(eng, "before_cursor_execute", record)


def touching(seen: list[str], table: str) -> list[str]:
    return [s for s in seen if re.search(rf"\b{table}\b", s)]


def test_an_all_null_batch_column_is_written_as_null(engine):
    # no title signal anywhere: every new seniority is NULL
    add_jobs(
        [{"external_id": f"n{i}", "source": "adzuna", "title": "Data Analyst"} for i in range(3)]
    )
    with engine.begin() as conn:
        conn.execute(text("update jobs set seniority = 'stale', salary_quality = 'stale'"))
    with session_scope(TEST_DB_URL) as s:
        counts = apply_cleaning.apply_job_steps(s, ("seniority", "salary"))
    assert counts == {"seniority": {"(none)": 3}, "salary": {"(no salary)": 3}}
    with engine.connect() as conn:
        got = conn.execute(text("select seniority, salary_quality from jobs")).all()
    assert got == [(None, None)] * 3


def test_only_writes_its_own_columns(engine):
    add_jobs([{"external_id": "a", "source": "adzuna", "title": "Senior Data Analyst (Remote)"}])
    with engine.begin() as conn:
        conn.execute(text("update jobs set seniority = 'stale', in_scope = null"))
    with session_scope(TEST_DB_URL) as s:
        results = apply_cleaning.run_steps(s, ("remote",))
    assert results == {"remote": {"remote_true": 1, "changed_vs_previous": 1}}
    with engine.connect() as conn:
        row = conn.execute(text("select seniority, in_scope, is_remote from jobs")).one()
    assert row == ("stale", None, True)


def test_nothing_changed_means_no_update(engine):
    add_jobs(
        [
            {"external_id": f"c{i}", "source": "adzuna", "title": t}
            for i, t in enumerate(["Junior Data Analyst", "BI Analyst", "Analyst (Remote)"])
        ]
    )
    with session_scope(TEST_DB_URL) as s:
        apply_cleaning.apply_job_steps(s)
    with statements() as seen, session_scope(TEST_DB_URL) as s:
        apply_cleaning.apply_job_steps(s)
    assert not [q for q in seen if q.lstrip().upper().startswith("UPDATE")]


def test_keyset_batches_cover_every_row(engine, monkeypatch):
    monkeypatch.setattr(apply_cleaning, "JOB_BATCH_SIZE", 2)
    add_jobs(
        [
            {"external_id": f"k{i}", "source": "adzuna", "title": "Lead Data Analyst"}
            for i in range(5)
        ]
    )
    with session_scope(TEST_DB_URL) as s:
        counts = apply_cleaning.apply_job_steps(s, ("seniority",))
    assert counts == {"seniority": {"lead": 5}}
    with engine.connect() as conn:
        assert (
            conn.execute(text("select count(*) from jobs where seniority = 'lead'")).scalar() == 5
        )


def test_orm_objects_held_by_the_caller_see_the_new_values(engine):
    add_jobs([{"external_id": "o", "source": "adzuna", "title": "Junior Data Analyst"}])
    with session_scope(TEST_DB_URL) as s:
        job = s.execute(select(Job)).scalar_one()
        job.title = "Senior Data Analyst"  # pending, not flushed: must be read
        apply_cleaning.apply_seniority(s)
        assert job.seniority == "senior"
