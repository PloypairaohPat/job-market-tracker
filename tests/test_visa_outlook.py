"""Integration tests for v_job_visa_outlook and the scan CLI's query/format.

One synthetic job per bucket, plus precedence (closed beats strong).
"""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.cleaning.apply_cleaning import apply_companies, apply_visa
from src.models import Company, Job
from src.utils.db import session_scope
from src.visa.scan import fetch_outlook, format_job, write_csv
from tests.conftest import reset_schema
from tests.visa_helpers import insert_lca, lca

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

NEUTRAL = "Build dashboards in SQL and Tableau for the analytics team."

# external_id -> (company, description, in_scope)
JOBS = {
    "closed-precedence": (
        "FAKE Northfield University",  # cap-exempt hint alone would be strong ...
        "Analyze enrollment data. Must be a U.S. citizen.",  # ... but the posting says no
        True,
    ),
    "closed-wont-sponsor": (
        "FAKECO Analytics LLC",  # >=3 analytics LCAs would be strong ...
        f"{NEUTRAL} We are unable to sponsor visas.",
        True,
    ),
    "strong-lca": ("FAKECO Analytics LLC", NEUTRAL, True),
    "strong-posting": ("FAKE Sponsor Friendly Inc", f"{NEUTRAL} Visa sponsorship available.", True),
    "strong-cap-exempt": ("FAKE Lakeside Community College", NEUTRAL, True),
    "possible": ("FAKE Widgets Corp", NEUTRAL, True),
    "possible-below-threshold": ("FAKE Two Filings LLC", NEUTRAL, True),
    "unknown": ("FAKE Nobody LLC", NEUTRAL, True),
    "out-of-scope": ("FAKECO Analytics LLC", NEUTRAL, False),
}


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    with session_scope(TEST_DB_URL) as session:
        companies = {}
        for name, _, _ in JOBS.values():
            if name not in companies:
                companies[name] = Company(canonical_name=name, raw_names=[name])
                session.add(companies[name])
        session.flush()
        for ext_id, (name, desc, in_scope) in JOBS.items():
            session.add(
                Job(
                    external_id=ext_id,
                    source="adzuna",
                    title=f"Data Analyst {ext_id}",
                    description=desc,
                    company_id=companies[name].id,
                    in_scope=in_scope,
                    redirect_url=f"https://example.invalid/{ext_id}",
                )
            )
        insert_lca(
            session,
            [lca("FAKECO Analytics LLC") for _ in range(3)]  # 3 analytics new-employment
            + [lca("FAKE Widgets Corp", soc_code="15-1252.00", new_employment=0)]
            + [lca("FAKE Two Filings LLC") for _ in range(2)]  # analytics, but only 2
            + [lca("FAKE Nobody LLC", case_status="Denied")],  # matched, never certified
        )
    with session_scope(TEST_DB_URL) as session:
        apply_companies(session, tmp_path / "candidates.csv")
        apply_visa(session)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def _buckets(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select j.external_id, o.bucket from v_job_visa_outlook o "
                "join jobs j on j.id = o.job_id"
            )
        ).all()
    return dict(rows)


def test_one_job_per_bucket_and_precedence(db):
    assert _buckets(db) == {
        "closed-precedence": "closed",
        "closed-wont-sponsor": "closed",
        "strong-lca": "strong",
        "strong-posting": "strong",
        "strong-cap-exempt": "strong",
        "possible": "possible",
        "possible-below-threshold": "possible",
        "unknown": "unknown",
        # out-of-scope job is not in the view at all
    }


def test_scan_filters_formats_and_exposes_only_aggregates(db, tmp_path):
    with session_scope(TEST_DB_URL) as session:
        strong = fetch_outlook(session, bucket="strong")
        everything = fetch_outlook(session, limit=None)
        limited = fetch_outlook(session, limit=2)
    assert {r["bucket"] for r in strong} == {"strong"} and len(strong) == 3
    assert [r["bucket"] for r in everything][0] == "strong"  # strong sorts first
    assert everything[-1]["bucket"] == "closed"  # closed sorts last
    assert len(limited) == 2

    lca_row = next(r for r in strong if r["title"].endswith("strong-lca"))
    out = format_job(lca_row)
    assert "[STRONG]" in out
    assert "3 certified H-1B" in out
    assert "https://example.invalid/strong-lca" in out
    assert "I-FAKE-" not in out  # never a case number

    path = tmp_path / "visa_scan.csv"
    write_csv(everything, path)
    content = path.read_text()
    assert "I-FAKE-" not in content
    assert content.splitlines()[0].startswith("job_id,source,title,company")


def test_unknown_reason_distinguishes_no_match(db):
    with db.connect() as conn:
        reason = conn.execute(
            text(
                "select o.bucket_reason from v_job_visa_outlook o join jobs j on j.id=o.job_id "
                "where j.external_id = 'unknown'"
            )
        ).scalar_one()
    assert "no certified H-1B" in reason
