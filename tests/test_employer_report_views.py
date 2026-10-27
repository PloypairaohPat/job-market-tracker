"""Report 3's four views: v_employer_postings, v_employer_sponsorship_match,
v_visa_outlook_summary and v_matched_employer_lca_wages."""

import os
import re
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from scripts.seed_demo_data import seed_full
from src.cleaning.company_normalizer import normalize_company_name
from src.reports.views import VIEWS_DIR
from tests.conftest import reset_schema
from tests.visa_helpers import insert_lca, lca

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]
ROW_LEVEL = {"job_id", "title", "redirect_url", "description", "case_number"}


def rows(engine, sql):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql))]


def columns(engine, view):
    return {
        r["column_name"]
        for r in rows(
            engine,
            f"select column_name from information_schema.columns where table_name = '{view}'",
        )
    }


@pytest.fixture
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    yield engine
    engine.dispose()


def company(engine, name):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "insert into companies (canonical_name, normalized_name, raw_names) "
                "values (:c, :n, '{}') returning id"
            ),
            {"c": name, "n": normalize_company_name(name)},
        ).scalar_one()


def job(engine, source, company_id=None, in_scope=True):
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into jobs (external_id, source, title, company_id, in_scope, is_remote) "
                "values (gen_random_uuid()::text, :s, 'Analyst', :c, :i, false)"
            ),
            {"s": source, "c": company_id, "i": in_scope},
        )


def lca_rows(engine, rows_):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        insert_lca(session, rows_)
        session.commit()


@pytest.fixture
def small(db):
    """A: 3 commercial postings, LCA history incl. analytics filings.
    B: 1 commercial posting, LCAs that don't count as certified H-1B.
    C: 2 commercial + 1 federal posting, a filing outside the 3-FY window.
    Plus 1 commercial posting with no company, and 1 out-of-scope federal one."""
    a, b, c = (company(db, n) for n in ("FAKECO Analytics", "FAKE Staffing", "FAKE Acme"))
    for _ in range(3):
        job(db, "adzuna", a)
    job(db, "adzuna", b)
    job(db, "adzuna", c)
    job(db, "adzuna", c)
    job(db, "adzuna", None)
    job(db, "usajobs", c)
    job(db, "usajobs", a, in_scope=False)
    lca_rows(
        db,
        [
            lca("FAKECO Analytics", wage_rate_of_pay_from=Decimal("100000")),
            lca(
                "FAKECO Analytics",
                wage_rate_of_pay_from=Decimal("50"),
                wage_unit_of_pay="Hour",  # 104,000 a year
            ),
            lca("FAKECO Analytics", soc_code="13-2011.00"),  # accountants: not analytics
            lca("FAKECO Analytics", case_status="Denied"),
            lca("FAKE Staffing", case_status="Certified - Withdrawn"),
            lca("FAKE Staffing", visa_class="E-3 Australian"),
            lca("FAKE Acme", fiscal_year=2022),  # outside 2024-2026
        ],
    )
    return db


def test_employer_postings_count_every_posting_once(small):
    got = {
        (r["market"], r["employer_key"]): r
        for r in rows(small, "select * from v_employer_postings")
    }
    assert {k: r["n_postings"] for k, r in got.items()} == {
        ("commercial", "fakeco analytics"): 3,
        ("commercial", "fake staffing"): 1,
        ("commercial", "fake acme"): 2,
        ("commercial", None): 1,
        ("federal", "fake acme"): 1,
    }
    commercial = got[("commercial", "fakeco analytics")]
    assert (commercial["market_n_postings"], commercial["market_n_employers"]) == (7, 3)
    assert commercial["employer_name"] == "FAKECO Analytics"
    assert got[("commercial", None)]["employer_name"] is None
    assert (
        got[("federal", "fake acme")]["market_n_postings"],
        got[("federal", "fake acme")]["market_n_employers"],
    ) == (1, 1)


def test_the_match_has_three_nested_levels(small):
    by_market = {r["market"]: r for r in rows(small, "select * from v_employer_sponsorship_match")}
    commercial, federal = by_market["commercial"], by_market["federal"]
    assert {k: commercial[k] for k in commercial if k != "market"} == {
        "n_postings": 7,
        "n_postings_no_employer": 1,
        "n_postings_matched": 4,  # A (3) and B (1): both have filings in the window
        "n_postings_certified_h1b": 3,  # B's withdrawn and E-3 filings don't count
        "n_postings_analytics_soc": 3,
        "n_employers": 3,
        "n_employers_matched": 2,
        "n_employers_certified_h1b": 1,
        "n_employers_analytics_soc": 1,
        "lca_rows_loaded": 7,
        "lca_window_start_fy": 2024,
        "lca_window_end_fy": 2026,
    }
    # C's only filing is outside the window: no match found
    assert (
        federal["n_postings"],
        federal["n_postings_matched"],
        federal["n_employers_matched"],
    ) == (1, 0, 0)


def test_wages_pool_matched_employers_analytics_filings(small):
    by_market = {r["market"]: r for r in rows(small, "select * from v_matched_employer_lca_wages")}
    commercial, federal = by_market["commercial"], by_market["federal"]
    assert (commercial["n_filings"], commercial["n_filings_with_wage"]) == (2, 2)
    assert (commercial["n_employers"], commercial["n_employers_with_wage"]) == (1, 1)
    assert (
        commercial["largest_employer_n_filings"] == 2 and federal["largest_employer_n_filings"] == 0
    )
    assert (
        commercial["p25_offered_annual_wage"],
        commercial["median_offered_annual_wage"],
        commercial["p75_offered_annual_wage"],
    ) == (101_000, 102_000, 103_000)
    assert federal["n_filings"] == 0 and federal["median_offered_annual_wage"] is None


def test_with_no_lca_data_every_view_still_has_a_row_per_market(db):
    job(db, "adzuna", company(db, "FAKECO Analytics"))
    job(db, "usajobs", company(db, "FAKE Agency"))
    match = {r["market"]: r for r in rows(db, "select * from v_employer_sponsorship_match")}
    assert set(match) == {"commercial", "federal"}
    for r in match.values():
        assert r["lca_rows_loaded"] == 0 and r["lca_window_end_fy"] is None
        assert r["n_postings_matched"] == r["n_employers_matched"] == 0
    wages = {r["market"]: r for r in rows(db, "select * from v_matched_employer_lca_wages")}
    assert set(wages) == {"commercial", "federal"}
    assert all(
        r["n_filings"] == 0 and r["median_offered_annual_wage"] is None for r in wages.values()
    )


def test_the_new_views_carry_no_row_level_columns(db):
    for view in (
        "v_employer_postings",
        "v_employer_sponsorship_match",
        "v_visa_outlook_summary",
        "v_matched_employer_lca_wages",
    ):
        cols = columns(db, view)
        assert cols and not (cols & ROW_LEVEL), view


def test_the_copied_lca_rules_match_v_employer_sponsorship():
    def block(view, start, end):
        sql = (VIEWS_DIR / f"{view}.sql").read_text()
        body = re.sub(r"--[^\n]*", "", sql)
        found = re.search(re.escape(start) + r".*?" + re.escape(end), body, re.S)
        assert found, (view, start)
        return re.sub(r"\s+", " ", found.group(0))

    for start, end in [
        ("analytics_soc(soc_prefix) AS (", ")\n),"),
        ("CASE LOWER(TRIM(c.wage_unit_of_pay))", "END"),
    ]:
        assert block("v_matched_employer_lca_wages", start, end) == block(
            "v_employer_sponsorship", start, end
        )
    wages = (VIEWS_DIR / "v_matched_employer_lca_wages.sql").read_text()
    assert "c.case_status = 'Certified'" in wages and "c.visa_class = 'H-1B'" in wages
    assert "BETWEEN w.end_fy - 2 AND w.end_fy" in wages


# --------------------------------------------------------------------- #
# cross-checks against the existing views on the full demo seed


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path_factory.mktemp("e") / "c.csv")
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def test_on_the_demo_the_new_views_agree_with_the_existing_ones(demo):
    market_jobs = {
        r["market"]: r["n"]
        for r in rows(demo, "select market, count(*) as n from v_market_jobs group by 1")
    }
    postings = rows(
        demo,
        "select market, sum(n_postings) as n, max(market_n_postings) as total from v_employer_postings group by 1",
    )
    assert (
        {r["market"]: r["n"] for r in postings}
        == {r["market"]: r["total"] for r in postings}
        == market_jobs
    )

    match = {r["market"]: r for r in rows(demo, "select * from v_employer_sponsorship_match")}
    (lca_count,) = rows(demo, "select count(*) as n from lca_cases")
    for market, r in match.items():
        assert r["n_postings"] == market_jobs[market] and r["lca_rows_loaded"] == lca_count["n"] > 0
        assert (
            r["n_postings_matched"]
            >= r["n_postings_certified_h1b"]
            >= r["n_postings_analytics_soc"]
        )
        assert (
            r["n_employers_matched"]
            >= r["n_employers_certified_h1b"]
            >= r["n_employers_analytics_soc"]
        )
    assert match["commercial"]["n_employers_matched"] > 0

    outlook = rows(
        demo,
        "select case when source = 'adzuna' then 'commercial' else 'federal' end as market, "
        "bucket, bucket_reason, count(*) as n from v_job_visa_outlook group by 1, 2, 3",
    )
    summary = rows(
        demo, "select market, bucket, bucket_reason, n_postings as n from v_visa_outlook_summary"
    )
    assert sorted(map(tuple, (r.values() for r in outlook))) == sorted(
        map(tuple, (r.values() for r in summary))
    )

    # the wage view's filing count is the sum of matched employers' analytics-SOC filings
    expected = rows(
        demo,
        "select p.market, coalesce(sum(s.certified_h1b_analytics_soc), 0) as n "
        "from (select distinct market, employer_key from v_employer_postings "
        "      where employer_key is not null) p "
        "join v_employer_sponsorship s on s.employer_key = p.employer_key and s.period = 'last_3_fy' "
        "group by p.market",
    )
    wages = {
        r["market"]: r["n_filings"]
        for r in rows(demo, "select * from v_matched_employer_lca_wages")
    }
    assert {r["market"]: r["n"] for r in expected if r["n"]} == {
        m: n for m, n in wages.items() if n
    }
