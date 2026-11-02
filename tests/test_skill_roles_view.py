"""v_skill_category_composition_roles: the composition over distinct roles.

Hand-built jobs, FAKE employers and titles, invented tags.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.cleaning.company_normalizer import normalize_company_name
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    yield engine
    engine.dispose()


def one(engine, sql, **params):
    with engine.begin() as conn:
        return conn.execute(text(sql), params).scalar_one()


def company(engine, name):
    return one(
        engine,
        "insert into companies (canonical_name, normalized_name, raw_names) "
        "values (:c, :n, '{}') returning id",
        c=name,
        n=normalize_company_name(name),
    )


def skill(engine, name, category):
    return one(
        engine,
        "insert into skills (name, category, aliases) values (:n, :c, '{}') returning id",
        n=name,
        c=category,
    )


def posting(engine, source, company_id, title, tags=(), in_scope=True):
    job = one(
        engine,
        "insert into jobs (external_id, source, title, title_normalized, company_id, in_scope, "
        "is_remote) values (gen_random_uuid()::text, :s, :t, lower(:t), :c, :i, false) "
        "returning id",
        s=source,
        t=title,
        c=company_id,
        i=in_scope,
    )
    for skill_id, confidence in tags:
        one(
            engine,
            "insert into job_skills (job_id, skill_id, confidence) values (:j, :s, :c) "
            "returning job_id",
            j=job,
            s=skill_id,
            c=confidence,
        )


def test_a_role_counts_each_category_once_however_often_it_is_reposted(db):
    sql, py, viz = (
        skill(db, "FAKE SQL", "language"),
        skill(db, "FAKE Py", "language"),
        skill(db, "FAKE Viz", "bi_tool"),
    )
    a, g = company(db, "FAKECO Reposts"), company(db, "FAKE Agency")
    for _ in range(3):  # one role reposted three times, two language skills each
        posting(db, "adzuna", a, "Data Analyst", [(sql, 0.9), (py, 0.9)])
    posting(db, "adzuna", a, "BI Analyst", [(viz, 0.9)])
    posting(db, "adzuna", a, "BI Analyst", [(sql, 0.85)])  # same role: adds language
    posting(db, "adzuna", a, "Report Writer", [(viz, 0.7)])  # under 0.8: a role, no category
    posting(db, "adzuna", None, "Data Analyst", [(viz, 0.9)])  # no company: no role
    posting(db, "usajobs", g, "Program Analyst", [(sql, 0.9)])
    posting(db, "usajobs", g, "Budget Analyst", [(viz, 0.9)], in_scope=False)

    with db.connect() as conn:
        got = {
            (r.market, r.category): (r.n_tags, float(r.pct_of_tags), r.market_n_jobs)
            for r in conn.execute(text("select * from v_skill_category_composition_roles"))
        }
        primary = {
            (r.market, r.category): r.n_tags
            for r in conn.execute(text("select * from v_skill_category_composition"))
        }
    assert got == {
        ("commercial", "language"): (2, 66.7, 3),  # data analyst + bi analyst
        ("commercial", "bi_tool"): (1, 33.3, 3),  # bi analyst (report writer's tag is 0.7)
        ("federal", "language"): (1, 100.0, 1),
    }
    # the primary view still counts every posting's tags
    assert primary[("commercial", "language")] == 7 and primary[("commercial", "bi_tool")] == 2


def test_the_roles_view_has_the_primary_views_shape(db):
    with db.connect() as conn:
        cols = [
            list(
                conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        f"where table_name = '{view}' order by ordinal_position"
                    )
                ).scalars()
            )
            for view in ("v_skill_category_composition", "v_skill_category_composition_roles")
        ]
    assert cols[0] == cols[1] == ["market", "category", "n_tags", "pct_of_tags", "market_n_jobs"]
