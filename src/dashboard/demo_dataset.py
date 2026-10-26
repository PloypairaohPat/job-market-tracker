"""Full synthetic demo dataset for the dashboards: `seed_demo_data.py --full`.

THIS IS DEMO DATA, NOT PIPELINE OUTPUT. It exists so every dashboard panel
has something to show without the owner's real database. Only a local
database whose name contains "demo" or "test" is accepted, and the run
starts by TRUNCATING every table in it.

What it builds, deterministically (fixed seed, and a fixed time of day
for every timestamp, so two runs on the same UTC day are identical):

1. Through the REAL ingestion path:
   - the Adzuna demo jobs (the two fixture pages per target query, the
     same 600 jobs `seed_demo_data.py` loads by default);
   - the 25 USAJobs fixture postings, via a fixture-backed client;
   - a handful of extra Adzuna-shaped postings at invented FAKE employers
     whose descriptions carry sponsorship, citizenship and clearance
     wording.
2. Written DIRECTLY with SQL, because the pipeline can't produce them
   (ingest_page stamps today's UTC date and has no clock injection):
   - DAYS days of snapshot history ending today, with ONE deliberately
     missing day (GAP_DAYS_AGO): every job gets a first-seen day and
     stays visible for a seeded number of days; first_seen_at and
     last_seen_at are rewritten to match;
   - an `ingestion_runs` row per source per day (none on the gap day),
     including one `failed` USAJobs run and one `skipped_budget` Adzuna
     run, whose days carry no snapshots for that source;
   - `lca_cases` rows for FAKE employers only, so v_job_visa_outlook has
     every bucket (closed, strong, possible, unknown).
3. Then cleaning (every apply_cleaning step) and skill extraction run as
   usual over the result.

Real company names from the Adzuna fixtures (Capital One, Deloitte, ...)
NEVER get LCA rows or sponsorship wording; every synthetic employer that
does contains "FAKE".
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url

from src.cleaning.apply_cleaning import ALL_STEPS, DEFAULT_CANDIDATES_OUT, run_steps
from src.cleaning.company_normalizer import normalize_company_name
from src.cleaning.extract_skills import extract_for_all_jobs, sync_taxonomy
from src.ingestion import ingest_adzuna, ingest_usajobs
from src.ingestion.adzuna_client import AdzunaClient
from src.ingestion.usajobs_client import USAJobsClient
from src.models import (
    Base,
    Company,
    IngestionRun,
    Job,
    JobSnapshot,
    JobVisaSignal,
    LcaCase,
    RawResponse,
)
from src.utils.db import session_scope

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

SEED = 20260101
DAYS = 28  # history window, today included
GAP_DAYS_AGO = 9  # the one day with no runs and no snapshots ("laptop off")
FAILED_USAJOBS_DAYS_AGO = 15
SKIPPED_ADZUNA_DAYS_AGO = 3
LONG_LIVED_JOBS = 40  # visible on every day of the window, so no day but the gap is empty
RUN_TIME = time(11, 15, tzinfo=UTC)  # 07:15 US Eastern (EDT): the scheduled-task time
_SAFE_HOSTS = {"localhost", "127.0.0.1"}


class UnsafeDemoDatabaseError(RuntimeError):
    pass


def assert_demo_database(database_url: str) -> None:
    """--full truncates every table: local host and a demo/test name only."""
    url = make_url(database_url)
    if (url.host or "") not in _SAFE_HOSTS:
        raise UnsafeDemoDatabaseError(
            f"refusing to seed host {url.host!r}: only localhost / 127.0.0.1"
        )
    name = url.database or ""
    if "demo" not in name and "test" not in name:
        raise UnsafeDemoDatabaseError(
            f"refusing to seed database {name!r}: its name must contain 'demo' or 'test'"
        )


# --------------------------------------------------------------------- #
# fixture-backed clients (no network)


class FixtureClient(AdzunaClient):
    """Serves the two Adzuna fixture pages instead of calling the network."""

    def __init__(self):
        super().__init__(app_id="demo", app_key="demo", min_request_interval=0.0)
        self._pages = [
            json.loads((FIXTURES / "adzuna_page_1.json").read_text()),
            json.loads((FIXTURES / "adzuna_page_2.json").read_text()),
        ]

    def iter_search(self, query, max_results=1000, results_per_page=50, **filters):
        # Give each query a distinct slice of IDs so the demo DB has volume.
        # NOTE: must be a *stable* hash — Python's hash() is randomized per
        # process (PYTHONHASHSEED), which broke seeder idempotency across runs.
        offset = int(hashlib.md5(query.encode()).hexdigest()[:6], 16) % 900_000
        for i, page in enumerate(self._pages, start=1):
            page = copy.deepcopy(page)
            for job in page["results"]:
                job["id"] = str(int(job["id"]) + offset)
            yield i, page


class FakeEmployerClient(AdzunaClient):
    """Serves one synthetic Adzuna-shaped page of FAKE-employer postings."""

    def __init__(self):
        super().__init__(app_id="demo", app_key="demo", min_request_interval=0.0)

    def iter_search(self, query, max_results=1000, results_per_page=50, **filters):
        yield 1, {"count": len(FAKE_POSTINGS), "results": [_fake_result(p) for p in FAKE_POSTINGS]}


class FixtureUSAJobsClient(USAJobsClient):
    """Serves the USAJobs fixture page once."""

    def __init__(self):
        super().__init__(
            api_key="demo", user_agent_email="fake@example.com", min_request_interval=0.0
        )
        self._page = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())

    def iter_search(self, query=None, max_results=1000, results_per_page=25, **filters):
        yield 1, copy.deepcopy(self._page)


# --------------------------------------------------------------------- #
# synthetic FAKE employers

_NEUTRAL = (
    "Build dashboards in SQL and Tableau, partner with stakeholders, and turn "
    "messy data into clear recommendations. Python a plus."
)

# (id, title, company, area, salary_min, salary_max, predicted, extra wording)
FAKE_POSTINGS = [
    ("9100000001", "Data Analyst (Cleared)", "FAKE Federal Contractor Inc",
     ["US", "Virginia", "Arlington County", "Arlington"], 85000, 105000, "0",
     "Active Secret clearance required. Must be a U.S. citizen."),
    ("9100000002", "Intelligence Data Analyst", "FAKE Federal Contractor Inc",
     ["US", "Virginia", "Fairfax County", "Fairfax"], 90000, 115000, "0",
     "TS/SCI with polygraph required."),
    ("9100000003", "Retail Data Analyst", "FAKE Quiet Retail Co",
     ["US", "Illinois", "Cook County", "Chicago"], 70000, 85000, "0",
     "We are unable to sponsor visas for this role now or in the future."),
    ("9100000004", "Data Analyst", "FAKE Sponsor Friendly Inc",
     ["US", "New York", "New York County", "New York"], 95000, 120000, "0",
     "Visa sponsorship available. OPT candidates welcome."),
    ("9100000005", "Senior Data Analyst", "FAKECO Analytics LLC",
     ["US", "New York", "New York County", "New York"], 120000, 145000, "0", ""),
    ("9100000006", "Junior Data Analyst", "FAKECO Analytics LLC",
     ["US", "Massachusetts", "Suffolk County", "Boston"], 72000, 88000, "1", ""),
    ("9100000007", "Institutional Research Analyst", "FAKE Northfield University",
     ["US", "Massachusetts", "Suffolk County", "Boston"], 68000, 82000, "0", ""),
    ("9100000008", "Business Intelligence Analyst", "FAKE Widgets Corp",
     ["US", "Washington", "King County", "Seattle"], None, None, "0", ""),
    ("9100000009", "Healthcare Data Analyst", "FAKE Lakeside Health Partners LLC",
     ["US", "California", "San Francisco County", "San Francisco"], 98000, 118000, "1", ""),
]  # fmt: skip


def _fake_result(p: tuple) -> dict:
    ext_id, title, company, area, smin, smax, predicted, wording = p
    return {
        "id": ext_id,
        "title": title,
        "description": f"FAKE demo posting. {_NEUTRAL} {wording}".strip(),
        "company": {"display_name": company},
        "location": {"area": area, "display_name": area[-1]},
        "salary_min": smin,
        "salary_max": smax,
        "salary_is_predicted": predicted,
        "created": "2026-01-05T09:00:00Z",
        "redirect_url": f"https://example.invalid/fake-demo/{ext_id}",
        "category": {"label": "IT Jobs", "tag": "it-jobs"},
        "contract_type": "permanent",
        "contract_time": "full_time",
    }


# employer -> list of (fiscal_year, status, visa_class, soc, new_employment, level, wage, unit, dependent)
_LCA_PLAN: dict[str, list[tuple]] = {
    # strong: >= 3 certified analytics-SOC new-employment H-1B LCAs
    "FAKECO Analytics LLC": [
        (2025, "Certified", "H-1B", "15-2051.01", 1, "II", "92000", "Year", False),
        (2025, "Certified", "H-1B", "15-2051.00", 1, "III", "118000", "Year", False),
        (2026, "Certified", "H-1B", "13-1161.00", 1, "I", "38", "Hour", False),
        (2026, "Certified", "H-1B", "15-2041.00", 1, "IV", "11500", "Month", False),
        (2026, "Certified-Withdrawn", "H-1B", "15-2051.01", 1, "II", "95000", "Year", False),
    ],
    # strong anyway via the cap-exempt name hint; LCAs add evidence
    "FAKE Northfield University": [
        (2025, "Certified", "H-1B", "15-2041.00", 1, "II", "74000", "Year", False),
        (2026, "Certified", "H-1B", "19-1042.00", 1, "I", "61000", "Year", False),
    ],
    # strong via the posting; one LCA for context
    "FAKE Sponsor Friendly Inc": [
        (2026, "Certified", "H-1B", "15-2051.01", 1, "II", "101000", "Year", False),
    ],
    # possible: one certified H-1B, not analytics, continued employment
    "FAKE Widgets Corp": [
        (2026, "Certified", "H-1B", "15-1252.00", 0, "III", "4200", "Bi-Weekly", False),
    ],
    # closed: the posting says it won't sponsor, despite analytics filings
    "FAKE Quiet Retail Co": [
        (2025, "Certified", "H-1B", "15-2051.01", 1, "II", "88000", "Year", False),
        (2026, "Certified", "H-1B", "13-1161.00", 1, "II", "79000", "Year", False),
    ],
    # unknown: matched employer, but nothing certified
    "FAKE Lakeside Health Partners LLC": [
        (2026, "Denied", "H-1B", "15-2051.01", 1, "II", "99000", "Year", False),
        (2026, "Withdrawn", "H-1B", "15-2051.01", 1, "II", "99000", "Year", False),
    ],
    # a heavy filer with no postings: shows in the employer aggregates only
    "FAKE Staffing Partners Inc": [
        (fy, "Certified", "H-1B", soc, 1, lvl, wage, "Year", True)
        for fy in (2024, 2025, 2026)
        for soc, lvl, wage in (
            ("15-1211.00", "I", "70000"),
            ("15-1252.00", "I", "76000"),
            ("15-2051.01", "II", "84000"),
            ("13-1111.00", "I", "66000"),
        )
    ],
    # treaty visa only: filtered out of "certified H-1B"
    "FAKE Down Under Data Pty": [
        (2026, "Certified", "E-3 Australian", "15-2051.01", 1, "II", "97000", "Year", False),
    ],
}


def _lca_rows(loaded_at: datetime) -> list[dict]:
    rows = []
    n = 0
    for employer, plan in _LCA_PLAN.items():
        for fy, status, visa, soc, new_emp, level, wage, unit, dependent in plan:
            n += 1
            rows.append(
                {
                    "case_number": f"I-FAKE-DEMO-{n:05d}",
                    "case_status": status,
                    "visa_class": visa,
                    "decision_date": date(fy - 1, 10, 1) + timedelta(days=(n * 37) % 330),
                    "job_title": "FAKE demo position",
                    "soc_code": soc,
                    "full_time_position": True,
                    "total_worker_positions": 1,
                    "new_employment": new_emp,
                    "continued_employment": 1 - new_emp,
                    "employer_name": employer,
                    "employer_city": "Fakeville",
                    "employer_state": "NY",
                    "wage_rate_of_pay_from": Decimal(wage),
                    "wage_unit_of_pay": unit,
                    "pw_wage_level": level,
                    "h1b_dependent": dependent,
                    "willful_violator": False,
                    "fiscal_year": fy,
                    "source_file": "synthetic-demo",
                    "loaded_at": loaded_at,
                    "employer_key": normalize_company_name(employer),
                }
            )
    return rows


# --------------------------------------------------------------------- #
# build


def _truncate_all(database_url: str) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"truncate {tables} restart identity cascade"))
    finally:
        engine.dispose()


def _at(day: date) -> datetime:
    return datetime.combine(day, RUN_TIME)


def _history(session, today: date, rng: random.Random) -> dict:
    """Rewrite snapshots and first/last_seen for every job; return per-day stats."""
    window = [today - timedelta(days=k) for k in range(DAYS - 1, -1, -1)]
    gap = today - timedelta(days=GAP_DAYS_AGO)
    no_source_day = {
        "adzuna": today - timedelta(days=SKIPPED_ADZUNA_DAYS_AGO),
        "usajobs": today - timedelta(days=FAILED_USAJOBS_DAYS_AGO),
    }
    session.execute(text("delete from job_snapshots"))
    stats: dict[tuple[date, str], dict[str, int]] = {}
    jobs = session.execute(select(Job).order_by(Job.id)).scalars().all()
    for i, job in enumerate(jobs):
        if i < LONG_LIVED_JOBS or job.source == "usajobs":
            first, last = window[0], today
        else:
            first = window[rng.randrange(DAYS)]
            last = min(today, first + timedelta(days=rng.randint(1, DAYS)))
        days = [d for d in window if first <= d <= last]
        days = [d for d in days if d != gap and d != no_source_day[job.source]] or [today]
        for d in days:
            session.add(
                JobSnapshot(
                    job_id=job.id,
                    snapshot_date=d,
                    is_active=True,
                    salary_min=job.salary_min,
                    salary_max=job.salary_max,
                )
            )
            s = stats.setdefault((d, job.source), {"jobs": 0, "new": 0})
            s["jobs"] += 1
        job.first_seen_at = _at(days[0])
        job.last_seen_at = _at(days[-1])
        stats.setdefault((days[0], job.source), {"jobs": 0, "new": 0})["new"] += 1
    return stats


def _runs(session, today: date, stats: dict, rng: random.Random) -> None:
    gap = today - timedelta(days=GAP_DAYS_AGO)
    for k in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=k)
        if day == gap:
            continue  # the laptop was off: no run at all
        for source in ("adzuna", "usajobs"):
            s = stats.get((day, source), {"jobs": 0, "new": 0})
            status, error, calls = "ok", None, rng.randint(24, 30)
            if source == "usajobs":
                calls = rng.randint(4, 8)
            if source == "usajobs" and k == FAILED_USAJOBS_DAYS_AGO:
                status, calls = "failed", 1
                error = "USAJobsError: Network error after 4 attempts (synthetic demo failure)"
            if source == "adzuna" and k == SKIPPED_ADZUNA_DAYS_AGO:
                status, calls = "skipped_budget", 0
                error = "skipped: used 975 of 1000 this month (synthetic demo)"
            started = _at(day) + (timedelta(minutes=6) if source == "usajobs" else timedelta())
            ok = status == "ok"
            session.add(
                IngestionRun(
                    source=source,
                    started_at=started,
                    finished_at=started + timedelta(minutes=5),
                    status=status,
                    calls_made=calls,
                    pages_fetched=max(0, calls - 6) if ok else 0,
                    jobs_processed=s["jobs"] if ok else 0,
                    jobs_new=s["new"] if ok else 0,
                    snapshot_date=day,
                    params={"synthetic_demo": True},
                    error=error,
                )
            )


def build_full_demo(
    database_url: str,
    today: date | None = None,
    candidates_out: Path = DEFAULT_CANDIDATES_OUT,
) -> None:
    """Truncate and rebuild the full demo dataset in `database_url`."""
    assert_demo_database(database_url)
    today = today or datetime.now(UTC).date()
    rng = random.Random(SEED)
    _truncate_all(database_url)

    # 1. real ingestion paths, fixture-backed (no network)
    ingest_adzuna.run_ingestion(
        FixtureClient(), queries=ingest_adzuna.TARGET_QUERIES, database_url=database_url
    )
    ingest_adzuna.run_ingestion(
        FakeEmployerClient(), queries=["demo fake employers"], database_url=database_url
    )
    ingest_usajobs.run_ingestion(
        FixtureUSAJobsClient(), queries=["data analyst"], database_url=database_url
    )

    # 2. synthetic history, run log and LCA rows (direct SQL: demo only)
    anchor = _at(today)
    with session_scope(database_url) as session:
        stats = _history(session, today, rng)
        _runs(session, today, stats, rng)
        session.execute(LcaCase.__table__.insert(), _lca_rows(anchor))
        session.execute(update(RawResponse).values(fetched_at=anchor))
        session.execute(update(Company).values(created_at=anchor))

    # 3. cleaning + skills, exactly as the daily runner does
    with session_scope(database_url) as session:
        run_steps(session, ALL_STEPS, candidates_out)
    with session_scope(database_url) as session:
        extract_for_all_jobs(session, sync_taxonomy(session))
        session.execute(update(JobVisaSignal).values(classified_at=anchor))
