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


def add_raw_page(engine, items: list[tuple[str, list[str]]]) -> int:
    import json

    response = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectId": ext,
                    "MatchedObjectDescriptor": {"UserArea": {"Details": {"KeyRequirements": req}}},
                }
                for ext, req in items
            ]
        }
    }
    with engine.begin() as conn:
        return conn.execute(
            text(
                "insert into raw_responses (source, endpoint, params, response) "
                "values ('usajobs', 'search', '{}', cast(:r as jsonb)) returning id"
            ),
            {"r": json.dumps(response)},
        ).scalar_one()


def test_visa_reads_raw_pages_once_per_batch_not_per_job(engine, monkeypatch):
    citizen = ["U.S. Citizenship is required."]
    pages = [
        add_raw_page(engine, [(f"u{p}{k}", citizen if k == 0 else []) for k in range(3)])
        for p in range(3)
    ]
    add_jobs(
        [
            {
                "external_id": f"u{p}{k}",
                "source": "usajobs",
                "title": "Management Analyst",
                "raw_response_id": pages[p],
            }
            for p in range(3)
            for k in range(3)
        ]
        + [{"external_id": "adz", "source": "adzuna", "title": "Data Analyst"}]
    )
    monkeypatch.setattr(apply_cleaning, "VISA_BATCH_SIZE", 4)  # 10 jobs: 3 batches
    with statements() as seen, session_scope(TEST_DB_URL) as s:
        dist = apply_cleaning.apply_visa(s)
    assert len(touching(seen, "raw_responses")) <= 3  # at most one per batch
    assert len([q for q in touching(seen, "job_visa_signals") if "INSERT" in q]) == 3
    assert dist["restriction:citizenship"] == 3  # the first job on each page
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from job_visa_signals")).scalar() == 10


# --------------------------------------------------------------------- #
# E3 skills


def tiny_taxonomy(sql_conf: float = 0.9):
    import re as _re

    from src.cleaning.skill_extractor import SkillDef, SkillExtractor

    return SkillExtractor(
        [
            SkillDef("sql", "language", sql_conf, _re.compile(r"\bsql\b", _re.I)),
            SkillDef("tableau", "bi_tool", 0.8, _re.compile(r"\btableau\b", _re.I)),
        ]
    )


def skill_ids(engine) -> dict[str, int]:
    with engine.begin() as conn:
        for name in ("sql", "tableau"):
            conn.execute(
                text("insert into skills (name, category, aliases) values (:n, 'x', '{}')"),
                {"n": name},
            )
        return dict(conn.execute(text("select name, id from skills")).all())


def links(engine) -> set[tuple[str, str, str]]:
    with engine.connect() as conn:
        return {
            (ext, name, str(conf))
            for ext, name, conf in conn.execute(
                text(
                    "select j.external_id, s.name, js.confidence from job_skills js "
                    "join jobs j on j.id = js.job_id join skills s on s.id = js.skill_id"
                )
            )
        }


def test_skills_keyset_batches_converge_and_update_confidence(engine, monkeypatch):
    from src.cleaning import extract_skills

    monkeypatch.setattr(extract_skills, "BATCH_SIZE", 2)
    ids = skill_ids(engine)
    add_jobs(
        [
            {"external_id": f"s{i}", "source": "adzuna", "title": "Analyst", "description": d}
            for i, d in enumerate(["SQL", "Tableau", "SQL and Tableau", None, "sql"])
        ]
    )
    with session_scope(TEST_DB_URL) as s:
        assert extract_skills.extract_for_all_jobs(s, ids, 0.0, tiny_taxonomy()) == (5, 5)
    assert links(engine) == {
        ("s0", "sql", "0.90"),
        ("s1", "tableau", "0.80"),
        ("s2", "sql", "0.90"),
        ("s2", "tableau", "0.80"),
        ("s4", "sql", "0.90"),
    }

    # a changed confidence is rewritten; a dropped match is deleted
    with engine.begin() as conn:
        conn.execute(text("update jobs set description = 'SQL' where external_id = 's2'"))
    with session_scope(TEST_DB_URL) as s:
        extract_skills.extract_for_all_jobs(s, ids, 0.0, tiny_taxonomy(sql_conf=0.7))
    assert links(engine) == {
        ("s0", "sql", "0.70"),
        ("s1", "tableau", "0.80"),
        ("s2", "sql", "0.70"),
        ("s4", "sql", "0.70"),
    }

    # converged: a second run writes nothing
    with statements() as seen, session_scope(TEST_DB_URL) as s:
        assert extract_skills.extract_for_all_jobs(s, ids, 0.0, tiny_taxonomy(0.7)) == (5, 4)
    writes = [q for q in touching(seen, "job_skills") if not q.lstrip().startswith("SELECT")]
    assert writes == []
