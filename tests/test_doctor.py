"""The laptop doctor (src/doctor.py): every check's PASS and problem paths.

The outside world is faked: .env files live in a temp root, schtasks and
git output are invented samples, and the database checks run against the
local test database only. Secret-looking values are FAKE and must never
appear in the output.
"""

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src import doctor
from src.doctor import FAIL, INFO, PASS, SKIP, WARN, Context
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[1]

FAKE_PW = "FAKEdbpw-77"
FAKE_VALUES = {
    "ADZUNA_APP_ID": "FAKEAPPID123",
    "ADZUNA_APP_KEY": "FAKEAPPKEY456",
    "USAJOBS_API_KEY": "FAKEUSAJOBSKEY789",
    "USAJOBS_USER_AGENT_EMAIL": "fake.owner@example.invalid",
}
GOOD_URL = f"postgresql+psycopg2://postgres:{FAKE_PW}@localhost:5432/jobmarket"


def make_root(tmp_path: Path, env: str | bytes | None = None) -> Path:
    """A temp project root: the real alembic.ini, migrations and views, plus a .env."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    for name in ("alembic.ini", "migrations", "sql"):
        (root / name).symlink_to(ROOT / name)
    if env is not None:
        target = root / ".env"
        target.write_bytes(env if isinstance(env, bytes) else env.encode("utf-8"))
    return root


def env_text(url: str = GOOD_URL, **values: str) -> str:
    return f"DATABASE_URL={url}\n" + "".join(f"{k}={v}\n" for k, v in values.items())


def ctx(root: Path, **kwargs) -> Context:
    kwargs.setdefault("environ", {})
    kwargs.setdefault("platform", "linux")
    kwargs.setdefault("git_status", lambda r: "")
    return Context(root=root, **kwargs)


def assert_no_secrets(*texts: str) -> None:
    for t in texts:
        for value in (FAKE_PW, *FAKE_VALUES.values()):
            assert value not in t


# --------------------------------------------------------------------- #
# 1 .env


def test_env_all_set_passes_and_names_only(tmp_path):
    c = ctx(make_root(tmp_path, env_text(**FAKE_VALUES)))
    f = doctor.check_env(c)
    assert f.status == PASS
    assert "uses postgresql+psycopg2://" in f.detail and "USAJOBS_API_KEY" in f.detail
    assert c.database_url == GOOD_URL
    assert_no_secrets(f.detail)


def test_env_missing_file_fails_with_copy_command(tmp_path):
    f = doctor.check_env(ctx(make_root(tmp_path)))
    assert f.status == FAIL
    assert f.fix.startswith('Copy-Item ".env.example" ".env"') and f.fix_posix.startswith("cp ")


def test_env_with_nul_bytes_fails_with_resave_fix(tmp_path):
    utf16 = env_text(**FAKE_VALUES).encode("utf-16")  # what PowerShell 5.1 `>>` writes
    f = doctor.check_env(ctx(make_root(tmp_path, utf16)))
    assert f.status == FAIL and "NUL bytes" in f.detail
    assert "re-save .env as UTF-8 in Notepad" in f.fix


def test_env_wrong_driver_fails_without_printing_the_url(tmp_path):
    c = ctx(make_root(tmp_path, env_text(f"postgresql://postgres:{FAKE_PW}@localhost/jobmarket")))
    f = doctor.check_env(c)
    assert f.status == FAIL and "starts with postgresql://" in f.detail
    assert "DATABASE_URL=postgresql+psycopg2://" in f.fix
    assert c.database_url == ""  # so the database checks are skipped
    assert_no_secrets(f.detail, f.fix)


def test_env_without_database_url_fails(tmp_path):
    f = doctor.check_env(ctx(make_root(tmp_path, "ADZUNA_APP_ID=x\n")))
    assert f.status == FAIL and "DATABASE_URL isn't set" in f.detail


def test_env_missing_source_names_warn_by_name(tmp_path):
    f = doctor.check_env(ctx(make_root(tmp_path, env_text(ADZUNA_APP_ID="FAKEAPPID123"))))
    assert f.status == WARN
    assert "not set: ADZUNA_APP_KEY, USAJOBS_API_KEY, USAJOBS_USER_AGENT_EMAIL" in f.detail
    assert f.fix.startswith('notepad ".env"')
    assert_no_secrets(f.detail)


def test_environment_wins_over_env_file_like_dotenv(tmp_path):
    c = ctx(
        make_root(tmp_path, env_text("postgresql://wrong")),
        environ={"DATABASE_URL": GOOD_URL, **FAKE_VALUES},
    )
    assert doctor.check_env(c).status == PASS and c.database_url == GOOD_URL


# --------------------------------------------------------------------- #
# 2 database (unreachable) and what it skips


def refusing_engine(url):
    raise ConnectionRefusedError(f"connection to {url} refused (password {FAKE_PW})")


def test_unreachable_database_fails_and_skips_what_needs_it(tmp_path):
    c = ctx(make_root(tmp_path, env_text(**FAKE_VALUES)), engine_factory=refusing_engine)
    findings = doctor.run_checks(c)
    by_id = {f.id: f for f in findings}
    assert [f.id for f in findings] == list(range(1, 11))
    assert by_id[2].status == FAIL and "not reachable at localhost:5432" in by_id[2].detail
    assert by_id[2].fix == (
        'open Docker Desktop and wait for "Engine running", then: docker compose up -d db'
    )
    assert {by_id[i].status for i in (3, 4, 5, 7)} == {SKIP}
    assert doctor.exit_code(findings) == 1
    assert_no_secrets(doctor.format_findings(findings), doctor.to_json(findings))


def test_no_usable_url_skips_the_database(tmp_path):
    findings = doctor.run_checks(ctx(make_root(tmp_path)))
    assert findings[1].status == SKIP and findings[2].status == SKIP


# --------------------------------------------------------------------- #
# 6 scheduled task (invented schtasks output)

SCHTASKS_SAMPLE = """
Folder: \\
HostName:                             FAKE-LAPTOP
TaskName:                             \\JobMarketTracker-Daily
Next Run Time:                        10/30/2026 7:15:00 AM
Status:                               Ready
Logon Mode:                           Interactive only
Last Run Time:                        10/29/2026 7:15:04 AM
Last Result:                          {result}
Author:                               FAKE-LAPTOP\\fakeuser
Task To Run:                          powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\\path\\to\\repo\\scripts\\windows\\run_daily.ps1"
"""


def schtasks(code=0, result="0"):
    return lambda: (code, SCHTASKS_SAMPLE.format(result=result))


def test_scheduled_task_skips_off_windows(tmp_path):
    assert doctor.check_scheduled_task(ctx(tmp_path)).status == SKIP


@pytest.mark.parametrize(
    "result,status,says",
    [
        ("0", PASS, "last result 0 (success)"),
        ("267011", PASS, "hasn't run yet"),
        ("1", WARN, "a step failed"),
        ("2", WARN, "the database was unreachable"),
        ("-2147020576", WARN, "Task Scheduler's own error code"),
        ("garbled", WARN, "couldn't read the last result"),
    ],
)
def test_scheduled_task_results(tmp_path, result, status, says):
    f = doctor.check_scheduled_task(
        ctx(tmp_path, platform="win32", run_schtasks=schtasks(result=result))
    )
    assert f.status == status and says in f.detail
    assert "last run 10/29/2026 7:15:04 AM, next run 10/30/2026 7:15:00 AM" in f.detail
    if status == WARN and result != "garbled":
        assert "logs\\daily-YYYY-MM-DD.log" in f.fix


def test_missing_scheduled_task_fails_with_register_command(tmp_path):
    missing = lambda: (1, "ERROR: The system cannot find the file specified.\n")  # noqa: E731
    f = doctor.check_scheduled_task(ctx(tmp_path, platform="win32", run_schtasks=missing))
    assert f.status == FAIL and f.fix == ".\\scripts\\windows\\register_daily_task.ps1"


def test_parse_schtasks_takes_key_value_lines():
    fields = doctor.parse_schtasks(SCHTASKS_SAMPLE.format(result="0"))
    assert fields["Last Result"] == "0" and fields["Status"] == "Ready"


# --------------------------------------------------------------------- #
# 8 file placement, 9 virtualenv, 10 uv.lock

PORCELAIN = """\
?? LCA_Disclosure_Data_FY2026_Q3.xlsx
?? notes/FAKE_export.csv
?? backup.dump
?? stray.log
?? data/lca/LCA_Disclosure_Data_FY2025_Q4.xlsx
?? logs/daily-2026-10-29.log
 M README.md
?? src/new_module.py
"""


def test_stray_files_outside_data_and_logs_fail_with_move_commands(tmp_path):
    f = doctor.check_file_placement(ctx(tmp_path, git_status=lambda r: PORCELAIN))
    assert f.status == FAIL
    assert doctor.stray_files(PORCELAIN) == [
        "LCA_Disclosure_Data_FY2026_Q3.xlsx",
        "notes/FAKE_export.csv",
        "backup.dump",
        "stray.log",
    ]
    assert 'Move-Item "LCA_Disclosure_Data_FY2026_Q3.xlsx" "data\\lca\\"' in f.fix
    assert 'Move-Item "notes\\FAKE_export.csv" "data\\"' in f.fix
    assert 'Move-Item "stray.log" "logs\\"' in f.fix
    assert 'mv "notes/FAKE_export.csv" "data/"' in f.fix_posix
    assert "move it into data\\" in f.detail


def test_clean_tree_passes_and_no_git_skips(tmp_path):
    assert doctor.check_file_placement(ctx(tmp_path)).status == PASS
    assert doctor.check_file_placement(ctx(tmp_path, git_status=lambda r: None)).status == SKIP


def test_other_virtualenv_is_info_only(tmp_path):
    other = ctx(tmp_path, environ={"VIRTUAL_ENV": str(tmp_path / ".virtualenvs" / ".venv")})
    f = doctor.check_virtualenv(other)
    assert f.status == INFO and "harmless; uv uses .venv" in f.detail
    assert f.fix.startswith("deactivate") and "python.terminal.activateEnvironment" in f.fix
    project = ctx(tmp_path, environ={"VIRTUAL_ENV": str(tmp_path / ".venv")})
    assert doctor.check_virtualenv(project).status == PASS
    assert doctor.check_virtualenv(ctx(tmp_path)).status == PASS


def test_untracked_uv_lock_is_info_and_never_says_commit(tmp_path):
    f = doctor.check_uv_lock(ctx(tmp_path, git_status=lambda r: "?? uv.lock\n"))
    assert f.status == INFO and "open decision" in f.detail and not f.fix
    assert doctor.check_uv_lock(ctx(tmp_path)).status == PASS


def test_a_crashing_check_is_a_fail_not_a_traceback(tmp_path):
    def boom(root):
        raise RuntimeError("FAKE crash")

    findings = doctor.run_checks(ctx(make_root(tmp_path), git_status=boom))
    assert findings[7].status == FAIL and "the check itself failed" in findings[7].detail


def test_cli_json_and_exit_code(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    monkeypatch.setattr(doctor, "Context", lambda: ctx(root))
    monkeypatch.setattr(sys, "argv", ["doctor", "--json"])
    with pytest.raises(SystemExit) as exit_:
        doctor.main()
    payload = json.loads(capsys.readouterr().out)
    assert exit_.value.code == payload["exit_code"] == 1  # no .env, no DATABASE_URL
    assert [c["id"] for c in payload["checks"]] == list(range(1, 11))
    assert {"id", "name", "status", "detail", "fix", "fix_posix"} == set(payload["checks"][0])


# --------------------------------------------------------------------- #
# database checks against the test database


@pytest.fixture
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def stamp_head(engine) -> str:
    head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    with engine.begin() as conn:
        conn.execute(text("create table if not exists alembic_version (version_num varchar(32))"))
        conn.execute(text("delete from alembic_version"))
        conn.execute(text("insert into alembic_version values (:v)"), {"v": head})
    return head


def db_ctx(tmp_path, **kwargs):
    root = make_root(tmp_path, env_text(TEST_DB_URL, **FAKE_VALUES))
    return ctx(root, **kwargs)


def findings_by_id(c):
    return {f.id: f for f in doctor.run_checks(c)}


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_migrations_and_views_fail_until_applied(db, tmp_path):
    by_id = findings_by_id(db_ctx(tmp_path))
    assert by_id[2].status == PASS
    assert by_id[3].status == FAIL and by_id[3].fix == "uv run alembic upgrade head"
    assert "no migration has been applied" in by_id[3].detail
    assert by_id[4].status == FAIL and by_id[4].fix == "uv run python scripts/apply_views.py"
    assert by_id[7].status == SKIP  # needs the views

    with db.begin() as conn:
        conn.execute(text("create table alembic_version (version_num varchar(32))"))
        conn.execute(text("insert into alembic_version values ('0000fakeold')"))
    by_id = findings_by_id(db_ctx(tmp_path / "b"))
    assert by_id[3].status == FAIL and "database at 0000fakeold" in by_id[3].detail

    head = stamp_head(db)
    apply_views(TEST_DB_URL)
    by_id = findings_by_id(db_ctx(tmp_path / "c"))
    assert by_id[3].status == PASS and head in by_id[3].detail
    assert by_id[4].status == PASS


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_daily_clock_reports_h1_h2_h7_and_progress(db, tmp_path):
    stamp_head(db)
    apply_views(TEST_DB_URL)
    f = findings_by_id(db_ctx(tmp_path))[5]
    assert f.status == FAIL and "H2 FAIL (no snapshots at all)" in f.detail
    assert "H1 adzuna WARN" in f.detail and "streak 0 of 60" in f.detail
    assert f.fix.startswith("Start-ScheduledTask -TaskName JobMarketTracker-Daily")
    assert f.fix_posix.startswith("./scripts/run_daily.sh")


def lca_row(n, fy, decided):
    return {
        "case_number": f"I-FAKE-DOC-{n:05d}",
        "case_status": "Certified",
        "visa_class": "H-1B",
        "decision_date": decided,
        "employer_name": "FAKECO Doctor Analytics",
        "employer_key": "fakeco doctor analytics",
        "wage_rate_of_pay_from": Decimal("90000"),
        "fiscal_year": fy,
        "source_file": "synthetic-test",
        "loaded_at": datetime(2026, 10, 1, tzinfo=UTC),
    }


def insert_lca(engine, rows):
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into lca_cases (case_number, case_status, visa_class, decision_date, "
                "employer_name, employer_key, wage_rate_of_pay_from, fiscal_year, source_file, "
                "loaded_at) values (:case_number, :case_status, :visa_class, :decision_date, "
                ":employer_name, :employer_key, :wage_rate_of_pay_from, :fiscal_year, "
                ":source_file, :loaded_at)"
            ),
            rows,
        )


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_lca_empty_partial_unloaded_and_complete(db, tmp_path):
    stamp_head(db)
    apply_views(TEST_DB_URL)
    f = findings_by_id(db_ctx(tmp_path / "a"))[7]
    assert f.status == WARN and "lca_cases is empty" in f.detail
    assert "src\\visa\\README.md, steps 1-3" in f.fix

    # FY2025 complete, FY2026 (the latest) partial: fine
    full = [lca_row(i, 2025, m) for i, m in enumerate(doctor.fiscal_months(2025))]
    partial = [lca_row(100 + i, 2026, m) for i, m in enumerate(doctor.fiscal_months(2026)[:9])]
    insert_lca(db, full + partial)
    f = findings_by_id(db_ctx(tmp_path / "b"))[7]
    assert f.status == PASS, f.detail
    assert "FY2025: 12 cases, 12 months" in f.detail and "FY2026: 9 cases, 9 months" in f.detail

    # a non-latest FY with two months missing, and a file whose FY isn't loaded
    gappy = [
        m for m in doctor.fiscal_months(2024) if m not in (date(2023, 10, 1), date(2024, 1, 1))
    ]
    insert_lca(db, [lca_row(200 + i, 2024, m) for i, m in enumerate(gappy)])
    c = db_ctx(tmp_path / "c")
    (c.root / "data" / "lca").mkdir(parents=True)
    (c.root / "data" / "lca" / "LCA_Disclosure_Data_FY2023_Q4.xlsx").write_bytes(b"FAKE")
    (c.root / "data" / "lca" / "LCA_Disclosure_Data_FY2025_Q1.xlsx").write_bytes(b"FAKE")
    f = findings_by_id(c)[7]
    assert f.status == WARN
    assert "FY2024 has 10 of 12 months (missing 2023-10, 2024-01)" in f.detail
    assert "LCA_Disclosure_Data_FY2023_Q4.xlsx looks unloaded (FY2023 not in lca_cases)" in f.detail
    assert "FY2025_Q1" not in f.detail  # its FY is loaded
    assert f.fix == (
        'uv run python -m src.visa.lca_loader --file "data\\lca\\LCA_Disclosure_Data_FY2023_Q4.xlsx" '
        "--fiscal-year 2023"
    )


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_doctor_is_read_only(db, tmp_path):
    stamp_head(db)
    apply_views(TEST_DB_URL)
    with db.connect() as conn:
        before = conn.execute(text("select count(*) from pg_stat_user_tables")).scalar_one()
    doctor.run_checks(db_ctx(tmp_path))
    with db.connect() as conn:
        assert conn.execute(text("select count(*) from job_snapshots")).scalar_one() == 0
        assert conn.execute(text("select count(*) from pg_stat_user_tables")).scalar_one() == before


# --------------------------------------------------------------------- #
# end to end on the full demo seed


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_end_to_end_on_the_demo_seed(db, tmp_path):
    from scripts.seed_demo_data import seed_full

    seed_full(TEST_DB_URL, candidates_out=tmp_path / "candidates.csv")
    stamp_head(db)
    findings = doctor.run_checks(db_ctx(tmp_path, now=datetime.now(UTC)))
    statuses = {f.id: f.status for f in findings}
    # 5 and 7 WARN by design of the demo data: it seeds one missing day
    # (H7 lists it), and its synthetic LCA rows span a few months per FY
    assert statuses == {
        1: PASS,
        2: PASS,
        3: PASS,
        4: PASS,
        5: WARN,
        6: SKIP,
        7: WARN,
        8: PASS,
        9: PASS,
        10: PASS,
    }
    gap = (datetime.now(UTC).date() - timedelta(days=9)).isoformat()
    assert f"H7 WARN (1 day(s) without a snapshot in the last 14 days: {gap})" in findings[4].detail
    assert doctor.exit_code(findings) == 0
    out = doctor.format_findings(findings)
    assert "nan" not in out and "None" not in out
    assert_no_secrets(out, doctor.to_json(findings))
