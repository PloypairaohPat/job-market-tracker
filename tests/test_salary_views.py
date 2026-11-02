"""Report 4's views: v_salary_population and v_salary_skill_coverage.

Hand-built jobs with invented salaries and FAKE titles, plus the full demo
seed for the totals cross-check.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.reports.guardrails import SALARY_FLOOR
from src.reports.views import VIEWS_DIR
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


def rows(engine, sql):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql))]


@pytest.fixture
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    yield engine
    engine.dispose()


def add_job(engine, quality="ok", currency="USD", period="year", predicted=False, source="adzuna"):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "insert into jobs (external_id, source, title, salary_min, salary_max, "
                "salary_quality, salary_currency, salary_period, salary_is_predicted, is_remote) "
                "values (gen_random_uuid()::text, :s, 'FAKE Analyst', 80000, 100000, :q, :c, :p, "
                ":pr, false) returning id"
            ),
            {"s": source, "q": quality, "c": currency, "p": period, "pr": predicted},
        ).scalar_one()


def add_skill(engine, name):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "insert into skills (name, category, aliases) values (:n, 'language', '{}') returning id"
            ),
            {"n": name},
        ).scalar_one()


def tag(engine, job_id, skill_id, confidence=0.9):
    with engine.begin() as conn:
        conn.execute(
            text("insert into job_skills (job_id, skill_id, confidence) values (:j, :s, :c)"),
            {"j": job_id, "s": skill_id, "c": confidence},
        )


def test_population_groups_every_commercial_posting_and_matches_the_clean_view(db):
    for _ in range(3):
        add_job(db)  # clean, disclosed
    add_job(db, predicted=True)  # clean, predicted
    add_job(db, quality=None, currency=None, period=None, predicted=None)  # no salary
    add_job(db, quality="suspect_outlier_high")
    add_job(db, currency="GBP")
    add_job(db, period="hour")
    add_job(db, source="usajobs")  # federal: not in it

    got = rows(db, "select * from v_salary_population")
    key = ("salary_quality", "salary_currency", "salary_period", "salary_is_predicted")
    by_group = {tuple(r[k] for k in key): r for r in got}
    assert {g: (r["n"], r["in_clean_population"]) for g, r in by_group.items()} == {
        ("ok", "USD", "year", False): (3, True),
        ("ok", "USD", "year", True): (1, True),
        (None, None, None, None): (1, False),  # NULLs are their own group
        ("suspect_outlier_high", "USD", "year", False): (1, False),
        ("ok", "GBP", "year", False): (1, False),
        ("ok", "USD", "hour", False): (1, False),
    }
    assert {r["market_n_postings"] for r in got} == {8}
    (clean,) = rows(db, "select count(*) as n from v_commercial_salary_clean")
    assert sum(r["n"] for r in got if r["in_clean_population"]) == clean["n"] == 4


def test_skill_coverage_per_basis_counts_tags_at_confidence_0_8(db):
    disclosed = [add_job(db) for _ in range(SALARY_FLOOR + 2)]
    predicted = [add_job(db, predicted=True) for _ in range(3)]
    sql, viz, low = add_skill(db, "FAKE SQL"), add_skill(db, "FAKE Viz"), add_skill(db, "FAKE Low")
    for job in disclosed[:SALARY_FLOOR]:  # exactly at the floor
        tag(db, job, sql)
    for job in disclosed[: SALARY_FLOOR - 1]:  # one short of it
        tag(db, job, viz)
    tag(db, disclosed[-1], low, confidence=0.7)  # under 0.8: not a tag
    tag(db, predicted[0], sql)
    add_job(db, quality="suspect_inverted")  # outside the clean population

    got = {r["basis"]: r for r in rows(db, "select * from v_salary_skill_coverage")}
    assert list(got) == ["employer-disclosed", "Adzuna-predicted"]
    pick = ("n_jobs", "n_jobs_tagged", "largest_skill_n", "n_skills_at_floor")
    assert tuple(got["employer-disclosed"][k] for k in pick) == (17, 15, 15, 1)
    assert tuple(got["Adzuna-predicted"][k] for k in pick) == (3, 1, 1, 0)


def test_skill_coverage_has_both_bases_with_no_data(db):
    got = rows(db, "select * from v_salary_skill_coverage")
    assert [(r["basis"], r["n_jobs"], r["largest_skill_n"]) for r in got] == [
        ("employer-disclosed", 0, 0),
        ("Adzuna-predicted", 0, 0),
    ]


def test_the_views_floor_is_the_salary_floor():
    sql = (VIEWS_DIR / "v_salary_skill_coverage.sql").read_text()
    assert f"s.n >= {SALARY_FLOOR}" in sql and "confidence >= 0.8" in sql


def test_the_views_carry_no_job_level_columns(db):
    for view in ("v_salary_population", "v_salary_skill_coverage"):
        cols = {
            r["column_name"]
            for r in rows(
                db,
                f"select column_name from information_schema.columns where table_name = '{view}'",
            )
        }
        assert cols and not cols & {"job_id", "title", "redirect_url", "description"}, view


def test_on_the_demo_the_clean_total_matches(tmp_path):
    from scripts.seed_demo_data import seed_full

    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    try:
        population = rows(engine, "select * from v_salary_population")
        (clean,) = rows(engine, "select count(*) as n from v_commercial_salary_clean")
        assert sum(r["n"] for r in population if r["in_clean_population"]) == clean["n"] > 0
        (commercial,) = rows(engine, "select count(*) as n from jobs where source = 'adzuna'")
        assert sum(r["n"] for r in population) == commercial["n"]
        coverage = {
            r["basis"]: r["n_jobs"] for r in rows(engine, "select * from v_salary_skill_coverage")
        }
        assert sum(coverage.values()) == clean["n"]  # the demo has no NULL predicted flag
    finally:
        engine.dispose()
        import src.utils.db as dbmod

        dbmod._engine = None
        dbmod._SessionFactory = None
