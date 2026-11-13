"""E0: production cleaning and skills code == the frozen reference, row for row.

Both sides start from the same deliberately wrong state (stale derived
values, missing and extra visa signals, stale and orphaned skill links) on
the full demo seed plus hand-built edge rows, run every step, and must leave
identical contents in every column and table the steps write:

    jobs          seniority, salary_quality, is_remote, in_scope, scope_reason
    locations     metro_area
    companies     normalized_name
    job_visa_signals   every column except classified_at (a timestamp)
    job_skills    job_id, skill_id, confidence

and return identical per-step counts. Every Part E commit must keep this
green; tests/reference_cleaning.py is the definition of the results.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.cleaning import apply_cleaning, extract_skills
from src.utils.db import session_scope
from tests import reference_cleaning as ref
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

NOW = datetime(2026, 3, 2, 12, tzinfo=UTC)

# Invented edge rows: no text at all, title only, a USAJobs row with no raw
# page, odd salaries, telework phrases, a citizenship line, a skills-heavy text.
EDGE_JOBS = [
    ("edge-1", "adzuna", "Data Analyst", None, None, None, None, None),
    ("edge-2", "adzuna", "Sr. BI Analyst (Remote)", "", None, 0, 0, "year"),
    ("edge-3", "usajobs", "IT Specialist (DATAMGT)", None, None, 50, 40, "hour"),
    (
        "edge-4",
        "usajobs",
        "Statistician",
        "short",
        "Telework: Ad hoc. Must be a U.S. citizen. SQL, Python and Tableau. "
        "This is a fully remote position.",
        90000,
        120000,
        "year",
    ),
    (
        "edge-6",
        "usajobs",
        "Management Analyst",
        "Summary only.",
        "This is a fully remote position. Duties include SQL reporting in Power BI.",
        None,
        None,
        None,
    ),
    (
        "edge-5",
        "adzuna",
        "Junior Analytics Engineer",
        "100% remote. dbt, Snowflake, SQL, Looker, Python; we do not sponsor visas.",
        None,
        2000000,
        None,
        "year",
    ),
]


@pytest.fixture
def seeded(tmp_path):
    from scripts.seed_demo_data import seed_full

    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "seed-candidates.csv")
    with engine.begin() as conn:
        for ext, source, title, desc, full, smin, smax, period in EDGE_JOBS:
            conn.execute(
                text(
                    "insert into jobs (external_id, source, title, description, "
                    "description_full, salary_min, salary_max, salary_period, is_remote, "
                    "first_seen_at, last_seen_at) values (:e, :s, :t, :d, :f, :mn, :mx, :p, "
                    "false, :now, :now)"
                ),
                {
                    "e": ext,
                    "s": source,
                    "t": title,
                    "d": desc,
                    "f": full,
                    "mn": smin,
                    "mx": smax,
                    "p": period,
                    "now": NOW,
                },
            )
        conn.execute(
            text(
                "insert into skills (name, category, aliases) "
                "values ('zz_left_the_taxonomy', 'tool', '{}')"
            )
        )
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod.dispose_engines()


def scramble(engine) -> None:
    """The same wrong starting state for both sides."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "update jobs set seniority = 'stale', salary_quality = 'stale', "
                "is_remote = not is_remote, in_scope = null, scope_reason = 'stale' "
                "where id % 3 = 0"
            )
        )
        conn.execute(text("update jobs set in_scope = not in_scope where id % 3 = 1"))
        conn.execute(text("update locations set metro_area = 'stale' where id % 2 = 0"))
        conn.execute(text("update companies set normalized_name = 'stale' where id % 2 = 1"))
        conn.execute(text("delete from job_visa_signals where job_id % 4 = 0"))
        conn.execute(text("update job_visa_signals set restriction = 'stale' where job_id % 4 = 1"))
        conn.execute(text("delete from job_skills where job_id % 5 = 0"))
        conn.execute(text("update job_skills set confidence = 0.42 where job_id % 5 = 1"))
        conn.execute(
            text(
                "insert into job_skills (job_id, skill_id, confidence) "
                "select j.id, s.id, 0.9 from jobs j cross join skills s "
                "where j.id % 7 = 0 and s.name in ('zz_left_the_taxonomy', 'SAS') "
                "on conflict do nothing"
            )
        )


def save_state(engine) -> None:
    """Copy the scrambled state aside, so both sides start from it exactly."""
    with engine.begin() as conn:
        for table in ("jobs", "locations", "companies", "job_visa_signals", "job_skills"):
            conn.execute(text(f"drop table if exists e0_saved_{table}"))
            conn.execute(text(f"create table e0_saved_{table} as select * from {table}"))


def restore_state(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "update jobs j set seniority = s.seniority, salary_quality = s.salary_quality, "
                "is_remote = s.is_remote, in_scope = s.in_scope, scope_reason = s.scope_reason "
                "from e0_saved_jobs s where s.id = j.id"
            )
        )
        conn.execute(
            text(
                "update locations l set metro_area = s.metro_area "
                "from e0_saved_locations s where s.id = l.id"
            )
        )
        conn.execute(
            text(
                "update companies c set normalized_name = s.normalized_name "
                "from e0_saved_companies s where s.id = c.id"
            )
        )
        for table in ("job_visa_signals", "job_skills"):
            conn.execute(text(f"delete from {table}"))
            conn.execute(text(f"insert into {table} select * from e0_saved_{table}"))


def snapshot(engine) -> dict[str, list]:
    queries = {
        "jobs": "select id, seniority, salary_quality, is_remote, in_scope, scope_reason "
        "from jobs order by id",
        "locations": "select id, metro_area from locations order by id",
        "companies": "select id, normalized_name from companies order by id",
        "job_visa_signals": "select job_id, restriction, restriction_reason, "
        "sponsorship_stance, sponsorship_reason, opt_mentioned, text_coverage, "
        "cap_exempt_hint, cap_exempt_reason from job_visa_signals order by job_id",
        "job_skills": "select job_id, skill_id, confidence from job_skills "
        "order by job_id, skill_id",
    }
    with engine.connect() as conn:
        return {name: [tuple(r) for r in conn.execute(text(q))] for name, q in queries.items()}


def run_reference(tmp_path: Path, min_confidence: float) -> dict:
    counts: dict = {}
    with session_scope(TEST_DB_URL) as s:
        counts["seniority"] = ref.apply_seniority(s)
        counts["salary"] = ref.apply_salary_quality(s)
        counts["remote"] = ref.apply_remote(s)
        counts["metro"] = ref.apply_metro(s)
        counts["companies"] = apply_cleaning.apply_companies(s, tmp_path / "ref.csv")
        counts["scope"] = ref.apply_scope(s)
        counts["visa"] = ref.apply_visa(s)
    with session_scope(TEST_DB_URL) as s:
        ids = extract_skills.sync_taxonomy(s)
        counts["skills"] = ref.extract_for_all_jobs(s, ids, min_confidence)
    return counts


def run_production(tmp_path: Path, min_confidence: float) -> dict:
    with session_scope(TEST_DB_URL) as s:
        counts = apply_cleaning.run_steps(s, apply_cleaning.ALL_STEPS, tmp_path / "prod.csv")
    with session_scope(TEST_DB_URL) as s:
        ids = extract_skills.sync_taxonomy(s)
        counts["skills"] = extract_skills.extract_for_all_jobs(s, ids, min_confidence)
    return counts


@pytest.mark.parametrize("min_confidence", [0.0, 0.8])
def test_production_matches_the_reference(seeded, tmp_path, min_confidence):
    scramble(seeded)
    save_state(seeded)
    ref_counts = run_reference(tmp_path, min_confidence)
    expected = snapshot(seeded)

    restore_state(seeded)
    prod_counts = run_production(tmp_path, min_confidence)
    actual = snapshot(seeded)

    assert prod_counts == ref_counts
    for table in expected:
        assert actual[table] == expected[table], table
    # the scramble really was undone (the test isn't comparing two no-ops)
    assert ref_counts["remote"]["changed_vs_previous"] > 0
    assert len(expected["job_visa_signals"]) == len(expected["jobs"])
    assert expected["job_skills"]


def test_a_second_production_run_changes_nothing(seeded, tmp_path):
    scramble(seeded)
    run_production(tmp_path, 0.0)
    first = snapshot(seeded)
    counts = run_production(tmp_path, 0.0)
    assert snapshot(seeded) == first
    assert counts["remote"]["changed_vs_previous"] == 0
