"""G1: one definition of the analysis population.

Every view that used to repeat the population filter inline now reads
v_analysis_population. tests/fixtures/analysis_population_reference/ holds
each of those views exactly as it was before the change; this test runs the
reference query and the current view on the same data and asserts the same
columns, the same column types and the same rows (as a multiset).

Two datasets: the full demo seed, and hand-built edge rows (in_scope true,
false and NULL on both sources, a source outside the population, a job with
no company, skill links either side of the 0.8 confidence floor, and
snapshot days with a gap). Invented data only.
"""

import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "tests" / "fixtures" / "analysis_population_reference"
VIEWS_DIR = ROOT / "sql" / "views"
REFACTORED = sorted(p.stem for p in REFERENCE_DIR.glob("*.sql"))
INLINE_FILTER = re.compile(r"source\s*=\s*'usajobs'\s+AND\s+(\w+\.)?in_scope", re.IGNORECASE)


def reference_query(view: str) -> str:
    sql = (REFERENCE_DIR / f"{view}.sql").read_text(encoding="utf-8")
    m = re.search(rf"CREATE OR REPLACE VIEW {view} AS\s*(.*?);?\s*$", sql, re.DOTALL)
    assert m, f"no view body in the reference file for {view}"
    return m.group(1)


def snapshot(engine, sql: str) -> tuple[list[str], list[int], Counter]:
    """Column names, column type OIDs and the multiset of rows."""
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        names = [d.name for d in cur.description]
        types = [d.type_code for d in cur.description]
        rows = Counter(tuple(r) for r in cur.fetchall())
        cur.close()
    finally:
        raw.close()
    return names, types, rows


# --------------------------------------------------------------------- #
# datasets


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    from scripts.seed_demo_data import seed_full

    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path_factory.mktemp("g1") / "c.csv")
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod.dispose_engines()


EDGE_JOBS = [
    # external_id, source, in_scope, company, days seen (October), skills (name, confidence)
    ("c-in", "adzuna", True, "Acme Analytics", [1, 2, 3], [("SQL", 0.9), ("Python", 0.8)]),
    ("c-out", "adzuna", False, "Acme Analytics", [2, 3], [("SQL", 0.79)]),
    ("c-null", "adzuna", None, None, [5], [("Tableau", 1.0)]),
    ("f-in", "usajobs", True, "Dept of Examples", [3], [("SQL", 0.95)]),
    ("f-out", "usajobs", False, "Dept of Examples", [3], [("Python", 0.9)]),
    ("f-null", "usajobs", None, "Dept of Examples", [3], [("SQL", 0.9)]),
    ("other", "greenhouse", True, "Acme Analytics", [1], [("SQL", 0.9)]),
]


@pytest.fixture(scope="module")
def edge():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    with engine.begin() as conn:
        companies = {}
        for name in {j[3] for j in EDGE_JOBS if j[3]}:
            companies[name] = conn.execute(
                text(
                    "insert into companies (canonical_name, normalized_name, raw_names) "
                    "values (:n, lower(:n), array[:n]) returning id"
                ),
                {"n": name},
            ).scalar_one()
        skills = {}
        for name, category in [("SQL", "language"), ("Python", "language"), ("Tableau", "bi")]:
            skills[name] = conn.execute(
                text(
                    "insert into skills (name, category, aliases) values (:n, :c, '{}') "
                    "returning id"
                ),
                {"n": name, "c": category},
            ).scalar_one()
        for ext, source, in_scope, company, days, job_skills in EDGE_JOBS:
            job_id = conn.execute(
                text(
                    "insert into jobs (external_id, source, title, title_normalized, "
                    "description, in_scope, is_remote, company_id, first_seen_at, "
                    "last_seen_at) values (:e, :s, 'Data Analyst', 'data analyst', "
                    "'Invented text', :i, false, :c, now(), now()) returning id"
                ),
                {"e": ext, "s": source, "i": in_scope, "c": companies.get(company)},
            ).scalar_one()
            for d in days:
                conn.execute(
                    text(
                        "insert into job_snapshots (job_id, snapshot_date, is_active) "
                        "values (:j, :d, true)"
                    ),
                    {"j": job_id, "d": date(2026, 10, d)},
                )
            for skill, confidence in job_skills:
                conn.execute(
                    text(
                        "insert into job_skills (job_id, skill_id, confidence) values (:j, :s, :c)"
                    ),
                    {"j": job_id, "s": skills[skill], "c": confidence},
                )
    yield engine
    engine.dispose()


# --------------------------------------------------------------------- #
# tests


def test_every_refactored_view_reads_the_population_view():
    assert REFACTORED, "no reference files found"
    for view in REFACTORED:
        sql = (VIEWS_DIR / f"{view}.sql").read_text(encoding="utf-8")
        body = re.sub(r"--[^\n]*", "", sql)
        assert "v_analysis_population" in body, view
        assert not INLINE_FILTER.search(body), f"{view} still repeats the filter inline"
        assert INLINE_FILTER.search(reference_query(view)), f"{view} reference lacks the filter"


def test_population_view_sorts_before_its_readers():
    names = sorted(p.name for p in VIEWS_DIR.glob("*.sql"))
    first = names.index("v_analysis_population.sql")
    for view in REFACTORED:
        assert names.index(f"{view}.sql") > first, view


def test_population_on_edge_rows(edge):
    with edge.connect() as conn:
        got = sorted(
            conn.execute(
                text(
                    "select j.external_id, p.market from v_analysis_population p "
                    "join jobs j on j.id = p.job_id"
                )
            ).all()
        )
    assert got == [
        ("c-in", "commercial"),
        ("c-null", "commercial"),
        ("c-out", "commercial"),
        ("f-in", "federal"),
    ]


@pytest.mark.parametrize("view", REFACTORED)
def test_view_matches_reference_on_edge_rows(edge, view):
    assert snapshot(edge, f"select * from {view}") == snapshot(edge, reference_query(view))


@pytest.mark.parametrize("view", REFACTORED)
def test_view_matches_reference_on_demo_seed(demo, view):
    current = snapshot(demo, f"select * from {view}")
    assert current == snapshot(demo, reference_query(view))
    assert sum(current[2].values()) > 0, f"{view} is empty on the demo seed"
