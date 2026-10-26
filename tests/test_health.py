"""Health check (src/pipeline/health.py) and v_ingestion_daily, with a fixed `now`."""

import json
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.models import IngestionRun, Job, JobSnapshot, JobVisaSignal
from src.pipeline import health as health_mod
from src.pipeline.health import current_streak, run_health
from src.utils.db import session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def day(n: int) -> date:
    """n days before TODAY."""
    return TODAY - timedelta(days=n)


# --------------------------------------------------------------------- #
# streak (unit)


def test_streak_counts_back_from_today_or_yesterday():
    assert current_streak([day(0), day(1), day(2)], TODAY) == 3
    assert current_streak([day(1), day(2)], TODAY) == 2  # ends yesterday: still alive
    assert current_streak([day(0), day(1), day(3), day(4)], TODAY) == 2  # one-day gap breaks it
    assert current_streak([day(2), day(3)], TODAY) == 0  # ended two days ago
    assert current_streak([], TODAY) == 0


# --------------------------------------------------------------------- #
# integration


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


_ids = iter(range(1, 1_000_000))


def seed_jobs(source: str, n: int, snapshot_days: list[date], classified: bool = True) -> list[int]:
    """n jobs of `source`, each snapshotted on every day in snapshot_days."""
    with session_scope(TEST_DB_URL) as session:
        jobs = []
        for _ in range(n):
            first = datetime.combine(min(snapshot_days), datetime.min.time(), tzinfo=UTC)
            job = Job(
                external_id=f"fake-{next(_ids)}",
                source=source,
                title="FAKE Data Analyst",
                first_seen_at=first + timedelta(hours=7),
                last_seen_at=datetime.combine(max(snapshot_days), datetime.min.time(), tzinfo=UTC),
            )
            session.add(job)
            jobs.append(job)
        session.flush()
        for job in jobs:
            for d in snapshot_days:
                session.add(JobSnapshot(job_id=job.id, snapshot_date=d, is_active=True))
            if classified:
                session.add(
                    JobVisaSignal(
                        job_id=job.id,
                        restriction="none_found",
                        sponsorship_stance="none_found",
                        opt_mentioned=False,
                        text_coverage="truncated",
                        cap_exempt_hint="unknown",
                    )
                )
        return [j.id for j in jobs]


def seed_jobs_per_day(source: str, counts: dict[date, int]) -> None:
    for d, n in counts.items():
        seed_jobs(source, n, [d])


def seed_run(source: str, status: str, finished_ago: timedelta, calls: int = 0) -> None:
    finished = NOW - finished_ago
    with session_scope(TEST_DB_URL) as session:
        session.add(
            IngestionRun(
                source=source,
                started_at=finished - timedelta(minutes=5),
                finished_at=finished,
                status=status,
                calls_made=calls,
                snapshot_date=finished.date(),
                params={},
            )
        )


def report(budget: int = 1000):
    with session_scope(TEST_DB_URL) as session:
        return run_health(session, NOW, budget)


def check(rep, check_id: str, contains: str = ""):
    matches = [c for c in rep.checks if c.id == check_id and contains in c.name]
    assert len(matches) == 1, (check_id, contains, rep.checks)
    return matches[0]


@pytest.mark.parametrize(
    "status,ago,expected",
    [
        ("ok", timedelta(hours=25), "PASS"),
        ("partial", timedelta(hours=26), "PASS"),
        ("ok", timedelta(hours=27), "FAIL"),
        ("failed", timedelta(hours=1), "FAIL"),  # rows exist, none ok
        ("skipped_budget", timedelta(hours=1), "FAIL"),
    ],
)
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h1_run_freshness(db, status, ago, expected):
    seed_run("adzuna", status, ago)
    assert check(report(), "H1", "adzuna").status == expected


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_history_with_no_run_rows(db):
    """Snapshots from before the run log: H1 WARNs with last_seen_at; nothing FAILs."""
    seed_jobs("adzuna", 3, [day(1), day(0)])
    seed_jobs("usajobs", 2, [day(0)])
    rep = report()
    h1 = check(rep, "H1", "adzuna")
    assert h1.status == "WARN" and "no run log yet" in h1.detail and str(TODAY) in h1.detail
    assert check(rep, "H1", "usajobs").status == "WARN"
    assert check(rep, "H2").status == "PASS"
    assert rep.exit_code == 0  # WARN never fails the check


@pytest.mark.parametrize(
    "latest,expected", [(day(0), "PASS"), (day(1), "WARN"), (day(2), "FAIL"), (None, "FAIL")]
)
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h2_snapshot_freshness(db, latest, expected):
    if latest is not None:
        seed_jobs("adzuna", 1, [latest])
    rep = report()
    assert check(rep, "H2").status == expected
    if expected == "FAIL":
        assert rep.exit_code == 1


@pytest.mark.parametrize(
    "prev,latest,expected",
    [(100, 40, "WARN"), (100, 50, "PASS"), (100, 60, "PASS"), (100, 140, "PASS")],
)
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h3_snapshot_volume(db, prev, latest, expected):
    seed_jobs_per_day("adzuna", {day(1): prev, day(0): latest})
    rep = report()
    assert check(rep, "H3", "adzuna").status == expected
    assert check(rep, "H3", "usajobs").status == "PASS"  # no history for that source


@pytest.mark.parametrize(
    "used,expected", [(849, "PASS"), (850, "WARN"), (999, "WARN"), (1000, "FAIL")]
)
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h4_budget(db, used, expected):
    seed_run("adzuna", "ok", timedelta(hours=1), calls=used)
    rep = report()
    assert check(rep, "H4").status == expected
    assert (rep.exit_code == 1) == (
        expected == "FAIL" or any(c.status == "FAIL" for c in rep.checks)
    )


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h5_cleaning_freshness(db):
    seed_jobs("adzuna", 2, [day(0)])
    assert check(report(), "H5").status == "PASS"
    seed_jobs("adzuna", 1, [day(0)], classified=False)
    h5 = check(report(), "H5")
    assert h5.status == "WARN" and h5.detail.startswith("1 job(s)")


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_h6_failed_runs(db):
    seed_run("usajobs", "failed", timedelta(days=8))
    assert check(report(), "H6").status == "PASS"  # outside the 7-day window
    seed_run("usajobs", "failed", timedelta(days=3))
    h6 = check(report(), "H6")
    assert h6.status == "WARN" and "usajobs: 1" in h6.detail


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_all_pass_exit_zero_and_progress(db):
    seed_jobs("adzuna", 4, [day(4), day(3), day(1), day(0)])  # gap at day(2)
    seed_jobs("usajobs", 2, [day(1), day(0)])
    seed_run("adzuna", "ok", timedelta(hours=2), calls=30)
    seed_run("usajobs", "ok", timedelta(hours=2))
    rep = report()
    assert [c.status for c in rep.checks] == ["PASS"] * len(rep.checks)
    assert rep.exit_code == 0
    progress = {c.name: c.detail for c in rep.progress}
    assert progress["unique jobs"] == "6 of 10,000"
    assert progress["snapshot days"] == "4 of 90"
    assert progress["current streak"] == "2 of 60 consecutive days"  # the gap breaks it
    assert progress["first snapshot"] == str(day(4))
    assert all(c.status == "INFO" for c in rep.progress)


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_health_is_read_only_and_cli_json(db, monkeypatch, capsys):
    seed_jobs("adzuna", 1, [day(5)])  # stale -> H2 FAIL
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setattr("sys.argv", ["health", "--json"])
    with pytest.raises(SystemExit) as exit_info:
        health_mod.main()
    assert exit_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall"] == "FAIL"
    assert {c["id"] for c in payload["checks"]} == {"H1", "H2", "H3", "H4", "H5", "H6"}
    with session_scope(TEST_DB_URL) as session:
        assert session.query(IngestionRun).count() == 0  # health wrote nothing


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_view_splits_by_source(db):
    apply_views(TEST_DB_URL)
    seed_jobs("adzuna", 3, [day(1), day(0)])
    seed_jobs("usajobs", 2, [day(0)])
    seed_run("adzuna", "ok", timedelta(hours=1), calls=12)
    with db.connect() as conn:
        rows = conn.execute(
            text(
                "select snapshot_date, source, snapshot_rows, distinct_jobs, new_jobs, n_runs, "
                "n_ok_runs, calls_made from v_ingestion_daily order by snapshot_date, source"
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        (day(1), "adzuna", 3, 3, 3, 0, 0, None),  # before any run row: zero runs, NULL calls
        (day(0), "adzuna", 3, 3, 0, 1, 1, 12),
        (day(0), "usajobs", 2, 2, 2, 0, 0, None),
    ]
