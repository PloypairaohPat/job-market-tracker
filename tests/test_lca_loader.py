"""LCA loader: unit tests for cell parsers + integration tests on synthetic files.

Every file here is built inside the test from invented values -- no real
LCA rows. The personal-data columns hold invented FAKE contacts so the
test can prove they never reach the database.
"""

import csv
import os
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, text

from src.visa.lca_loader import (
    COLUMN_MAP,
    MissingColumnsError,
    load_file,
    parse_date,
    parse_flag,
    parse_int,
    parse_wage,
)
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

# Columns real files carry that must NEVER be loaded, with invented values.
PERSONAL = {
    "EMPLOYER_POC_LAST_NAME": "FAKEPERSONLAST",
    "EMPLOYER_POC_FIRST_NAME": "FAKEPERSONFIRST",
    "EMPLOYER_POC_EMAIL": "fake.poc@example.invalid",
    "EMPLOYER_POC_PHONE": "5550000001",
    "AGENT_ATTORNEY_LAST_NAME": "FAKEATTORNEYLAST",
    "AGENT_ATTORNEY_EMAIL_ADDRESS": "fake.attorney@example.invalid",
    "LAWFIRM_NAME_BUSINESS_NAME": "FAKE Lawfirm Partners",
    "PREPARER_EMAIL": "fake.preparer@example.invalid",
}


def case(n: str, **overrides) -> dict:
    row = {
        "CASE_NUMBER": n,
        "CASE_STATUS": "Certified",
        "RECEIVED_DATE": "2025-11-03",
        "DECISION_DATE": "11/10/2025",
        "VISA_CLASS": "H-1B",
        "JOB_TITLE": "Data Analyst",
        "SOC_CODE": "15-2051.01",
        "SOC_TITLE": "Business Intelligence Analysts",
        "FULL_TIME_POSITION": "Y",
        "BEGIN_DATE": "2026-01-05",
        "TOTAL_WORKER_POSITIONS": "1",
        "NEW_EMPLOYMENT": "1",
        "CONTINUED_EMPLOYMENT": "0",
        "CHANGE_EMPLOYER": "0",
        "EMPLOYER_NAME": "FAKECO Analytics LLC",
        "TRADE_NAME_DBA": "",
        "EMPLOYER_CITY": "Fakeville",
        "EMPLOYER_STATE": "NY",
        "EMPLOYER_FEIN": "00-0000000",
        "NAICS_CODE": "541511",
        "WORKSITE_CITY": "New York",
        "WORKSITE_STATE": "NY",
        "WAGE_RATE_OF_PAY_FROM": "$85,000.00",
        "WAGE_RATE_OF_PAY_TO": "",
        "WAGE_UNIT_OF_PAY": "Year",
        "PREVAILING_WAGE": "80000",
        "PW_UNIT_OF_PAY": "Year",
        "PW_WAGE_LEVEL": "II",
        "H-1B_DEPENDENT": "N",
        "WILLFUL_VIOLATOR": "No",
        **PERSONAL,
    }
    row.update(overrides)
    return row


def write_csv(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    header = list(rows[0])
    ws.append(header)
    for r in rows:
        ws.append([r[h] for h in header])
    wb.save(path)
    return path


# --------------------------------------------------------------------- #
# unit: defensive cell parsers


@pytest.mark.parametrize(
    "raw,expected,ok",
    [
        ("Y", True, True),
        ("yes", True, True),
        ("N", False, True),
        (" No ", False, True),
        ("", None, True),
        (None, None, True),
        ("maybe", None, False),
    ],
)
def test_parse_flag(raw, expected, ok):
    assert parse_flag(raw) == (expected, ok)


@pytest.mark.parametrize(
    "raw,expected,ok",
    [
        ("$85,000.00", Decimal("85000.00"), True),
        ("42.5", Decimal("42.50"), True),
        (91000, Decimal("91000.00"), True),
        ("", None, True),
        ("$abc", None, False),
        ("85000 - 95000", None, False),
        ("-5", None, False),
    ],
)
def test_parse_wage(raw, expected, ok):
    assert parse_wage(raw) == (expected, ok)


def test_parse_date_and_int():
    assert parse_date("2025-10-01")[0].isoformat() == "2025-10-01"
    assert parse_date("10/1/2025")[0].isoformat() == "2025-10-01"
    assert parse_date("not a date") == (None, False)
    assert parse_int("3") == (3, True)
    assert parse_int(2.0) == (2, True)
    assert parse_int("1.5") == (None, False)
    assert parse_int("x") == (None, False)


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


def _all_text(engine) -> str:
    with engine.connect() as conn:
        rows = conn.execute(text("select * from lca_cases")).all()
    return "\n".join(str(tuple(r)) for r in rows)


@pytest.mark.parametrize("writer,suffix", [(write_csv, ".csv"), (write_xlsx, ".xlsx")])
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_file_loads_and_personal_data_never_reaches_db(db, tmp_path, writer, suffix):
    path = writer(
        tmp_path / f"LCA_FY2026_Q1{suffix}",
        [case("I-200-00001-000001"), case("I-200-00001-000002")],
    )
    result = load_file(path, 2026, database_url=TEST_DB_URL)
    assert result.rows_loaded == 2
    assert result.by_case_status == {"Certified": 2}
    assert result.by_visa_class == {"H-1B": 2}

    with db.connect() as conn:
        row = (
            conn.execute(text("select * from lca_cases where case_number = 'I-200-00001-000001'"))
            .mappings()
            .one()
        )
        columns = conn.execute(
            text(
                "select table_name, column_name from information_schema.columns where table_schema='public'"
            )
        ).all()
    assert row["employer_key"] == "fakeco analytics"
    assert row["wage_rate_of_pay_from"] == Decimal("85000.00")
    assert row["full_time_position"] is True and row["willful_violator"] is False
    assert row["decision_date"].isoformat() == "2025-11-10"
    assert row["naics_code"] == "541511"
    assert row["fiscal_year"] == 2026 and row["source_file"] == path.name

    # no personal-data column anywhere in the schema ...
    banned = ("poc", "attorney", "lawfirm", "preparer", "email", "phone")
    leaked = [(t, c) for t, c in columns if any(b in c.lower() for b in banned)]
    assert leaked == []
    # ... and no personal-data value anywhere in the loaded rows
    dumped = _all_text(db)
    for value in PERSONAL.values():
        assert value not in dumped


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_cumulative_quarter_reload_does_not_double_count(db, tmp_path):
    q2 = write_xlsx(
        tmp_path / "LCA_FY2026_Q2.xlsx", [case("A-1"), case("A-2", CASE_STATUS="Withdrawn")]
    )
    # Q3 is cumulative: repeats A-1 and A-2 (A-2 now Certified-Withdrawn) and adds A-3
    q3 = write_csv(
        tmp_path / "LCA_FY2026_Q3.csv",
        [case("A-1"), case("A-2", CASE_STATUS="Certified-Withdrawn"), case("A-3")],
    )
    load_file(q2, 2026, database_url=TEST_DB_URL)
    load_file(q3, 2026, database_url=TEST_DB_URL)
    load_file(q3, 2026, database_url=TEST_DB_URL)  # and re-running the same file is a no-op

    with db.connect() as conn:
        rows = dict(conn.execute(text("select case_number, case_status from lca_cases")).all())
        files = set(conn.execute(text("select source_file from lca_cases")).scalars())
    assert rows == {"A-1": "Certified", "A-2": "Certified-Withdrawn", "A-3": "Certified"}
    assert files == {"LCA_FY2026_Q3.csv"}  # latest file wins


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_bad_cells_are_counted_not_fatal(db, tmp_path):
    rows = [
        case("B-1", RECEIVED_DATE="31/31/2025", WAGE_RATE_OF_PAY_FROM="$abc"),
        case("B-2", **{"H-1B_DEPENDENT": "maybe"}, NEW_EMPLOYMENT="one"),
        case("", EMPLOYER_NAME="FAKE Orphan Row Inc"),  # no case number -> skipped
        case("B-1", JOB_TITLE="Senior Data Analyst"),  # duplicate within file -> last kept
    ]
    path = write_csv(tmp_path / "bad.csv", rows)
    result = load_file(path, 2026, database_url=TEST_DB_URL)

    assert result.rows_loaded == 2
    assert result.skipped_no_case_number == 1
    assert result.duplicate_case_numbers_in_file == 1
    assert result.bad_cells == {
        "received_date": 1,
        "wage_rate_of_pay_from": 1,
        "h1b_dependent": 1,
        "new_employment": 1,
    }
    with db.connect() as conn:
        b2 = conn.execute(
            text("select h1b_dependent, new_employment from lca_cases where case_number='B-2'")
        ).one()
        b1_title = conn.execute(
            text("select job_title from lca_cases where case_number='B-1'")
        ).scalar_one()
    assert tuple(b2) == (None, None)
    assert b1_title == "Senior Data Analyst"


def test_dry_run_writes_nothing_and_missing_required_column_fails(tmp_path):
    path = write_csv(tmp_path / "dry.csv", [case("D-1")])
    # dry run never opens a database connection, so no TEST_DATABASE_URL needed
    result = load_file(
        path, 2026, dry_run=True, database_url="postgresql+psycopg2://x@127.0.0.1:1/none_test"
    )
    assert result.rows_loaded == 1

    no_case = [{k: v for k, v in case("D-2").items() if k != "CASE_NUMBER"}]
    with pytest.raises(MissingColumnsError):
        load_file(write_csv(tmp_path / "nocase.csv", no_case), 2026, dry_run=True)


def test_column_map_has_no_personal_data_columns():
    banned = ("POC", "ATTORNEY", "LAWFIRM", "PREPARER", "EMAIL", "PHONE")
    assert not [c for c in COLUMN_MAP if any(b in c for b in banned)]
