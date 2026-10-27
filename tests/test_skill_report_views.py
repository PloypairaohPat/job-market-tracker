"""v_skill_text_basis and v_federal_skill_by_admission (report 1's two new views)."""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from scripts.seed_demo_data import seed_full
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

SKILLS = {"SQL": "language", "Statistics": "ml_stats", "Tableau": "bi_tool"}


@pytest.fixture
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    with engine.begin() as conn:
        for name, category in SKILLS.items():
            conn.execute(
                text("insert into skills (name, category, aliases) values (:n, :c, '{}')"),
                {"n": name, "c": category},
            )
    yield engine
    engine.dispose()


def add_job(engine, source, *, in_scope=True, reason=None, desc="", full=None, tags=()):
    """One job plus its skill tags: tags = [(skill name, confidence), ...]."""
    with engine.begin() as conn:
        job_id = conn.execute(
            text(
                "insert into jobs (external_id, source, title, description, description_full, "
                "in_scope, scope_reason, is_remote) values (gen_random_uuid()::text, :s, 'Analyst', "
                ":d, :f, :i, :r, false) returning id"
            ),
            {"s": source, "d": desc, "f": full, "i": in_scope, "r": reason},
        ).scalar_one()
        for name, confidence in tags:
            conn.execute(
                text(
                    "insert into job_skills (job_id, skill_id, confidence) "
                    "select :j, id, :c from skills where name = :n"
                ),
                {"j": job_id, "c": confidence, "n": name},
            )
    return job_id


def rows(engine, sql):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql))]


def test_text_basis_counts_what_the_extractor_read(db):
    add_job(db, "adzuna", desc="x" * 500, tags=[("SQL", 1.0), ("Tableau", 1.0)])
    add_job(db, "adzuna", desc="x" * 480, tags=[("SQL", 0.7)])  # below the confidence bar
    add_job(db, "adzuna", desc="x" * 200)
    fed = dict(in_scope=True, reason="series:Statistics", desc="y" * 400)
    add_job(db, "usajobs", full="z" * 6000, tags=[("Statistics", 1.0)], **fed)
    add_job(db, "usajobs", full="z" * 4000, **fed)
    add_job(db, "usajobs", in_scope=False, reason="category_excluded:Budget", full="z" * 9000)

    by_market = {r["market"]: r for r in rows(db, "select * from v_skill_text_basis")}
    commercial, federal = by_market["commercial"], by_market["federal"]
    assert (commercial["n_jobs"], commercial["n_full_text"], commercial["n_near_cap"]) == (3, 0, 2)
    assert (commercial["median_text_chars"], commercial["n_jobs_tagged"], commercial["n_tags"]) == (
        480,
        1,
        2,
    )
    # federal reads description_full: never "near the cap"; out-of-scope excluded
    assert (federal["n_jobs"], federal["n_full_text"], federal["n_near_cap"]) == (2, 2, 0)
    assert (federal["median_text_chars"], federal["n_jobs_tagged"], federal["n_tags"]) == (
        5000,
        1,
        1,
    )


def test_admission_routes_keep_zero_counts_and_drop_the_skill_count_suffix(db):
    for _ in range(2):
        add_job(db, "usajobs", reason="series:Operations Research", tags=[("Statistics", 0.9)])
    add_job(
        db, "usajobs", reason="skill_density:Management And Program Analysis:2", tags=[("SQL", 1.0)]
    )
    add_job(db, "usajobs", reason="skill_density:Management And Program Analysis:3")
    add_job(db, "usajobs", reason="series:Statistics", tags=[("Tableau", 0.5)])  # below the bar
    add_job(db, "usajobs", in_scope=False, reason="no_category", tags=[("Statistics", 1.0)])
    add_job(db, "adzuna", tags=[("Statistics", 1.0)])

    got = {
        (r["admission_route"], r["name"]): (
            r["n_jobs_tagged"],
            r["route_n_jobs"],
            float(r["pct_of_jobs"]),
        )
        for r in rows(db, "select * from v_federal_skill_by_admission")
    }
    assert got == {
        ("series:Operations Research", "Statistics"): (2, 2, 100.0),
        ("series:Operations Research", "SQL"): (0, 2, 0.0),
        ("series:Statistics", "Statistics"): (0, 1, 0.0),
        ("series:Statistics", "SQL"): (0, 1, 0.0),
        ("skill_density:Management And Program Analysis", "Statistics"): (0, 2, 0.0),
        ("skill_density:Management And Program Analysis", "SQL"): (1, 2, 50.0),
    }


def test_admission_routes_survive_when_no_federal_job_is_tagged(db):
    add_job(db, "usajobs", reason="series:Statistics")
    (row,) = rows(db, "select * from v_federal_skill_by_admission")
    assert (row["admission_route"], row["name"], row["n_jobs_tagged"], row["route_n_jobs"]) == (
        "series:Statistics",
        None,
        0,
        1,
    )


def test_on_the_demo_data_the_tag_totals_agree_across_views(tmp_path):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    try:
        composition = rows(
            engine,
            "select market, sum(n_tags) as n from v_skill_category_composition group by market",
        )
        basis = {r["market"]: r for r in rows(engine, "select * from v_skill_text_basis")}
        completeness = {
            r["market"]: r["n_jobs"] for r in rows(engine, "select * from v_field_completeness")
        }
        assert {r["market"]: r["n"] for r in composition} == {
            m: r["n_tags"] for m, r in basis.items()
        }
        assert {m: r["n_jobs"] for m, r in basis.items()} == completeness
        routes = rows(
            engine,
            "select admission_route, max(route_n_jobs) as n "
            "from v_federal_skill_by_admission group by 1",
        )
        assert sum(r["n"] for r in routes) == basis["federal"]["n_jobs"]
    finally:
        engine.dispose()
        import src.utils.db as dbmod

        dbmod._engine = None
        dbmod._SessionFactory = None
