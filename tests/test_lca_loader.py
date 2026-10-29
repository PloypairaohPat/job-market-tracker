"""LCA loader: unit tests for cell parsers + integration tests on synthetic files.

Every file here is built inside the test from invented values -- no real
LCA rows. The personal-data columns hold invented FAKE contacts so the
test can prove they never reach the database.
"""

import csv
import logging
import os
import sys
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.visa.lca_loader import (
    ALIASES,
    COLUMN_MAP,
    AmbiguousColumnsError,
    MissingColumnsError,
    OutsideFiscalYearError,
    fiscal_year_bounds,
    load_file,
    main,
    parse_date,
    parse_flag,
    parse_int,
    parse_wage,
    rekey_employers,
    summarize,
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


def spelled(row: dict, h1b_header: str) -> dict:
    """The same case with H-1B_DEPENDENT under another header spelling (or dropped)."""
    value = row["H-1B_DEPENDENT"]
    out = {k: v for k, v in row.items() if k != "H-1B_DEPENDENT"}
    if h1b_header:
        out[h1b_header] = value
    return out


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
        ("N/A", None, True),  # not applicable: NULL, not a bad cell
        ("NA", None, True),
        (" n/a ", None, True),
        ("maybe", None, False),
        ("N.A.", None, False),  # anything else unrecognized is still bad
        ("Unknown", None, False),
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


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_rekey_recomputes_employer_key(db, tmp_path):
    load_file(write_csv(tmp_path / "k.csv", [case("K-1")]), 2026, database_url=TEST_DB_URL)
    with db.begin() as conn:
        conn.execute(text("update lca_cases set employer_key = 'stale key'"))
    assert rekey_employers(TEST_DB_URL) == 1
    assert rekey_employers(TEST_DB_URL) == 0  # idempotent
    with db.connect() as conn:
        key = conn.execute(text("select employer_key from lca_cases")).scalar_one()
    assert key == "fakeco analytics"


# --------------------------------------------------------------------- #
# header aliases: DOL's files spell the H-1B dependency column H_1B_DEPENDENT


def test_aliases_are_exact_and_carry_no_personal_data():
    assert ALIASES["h1b_dependent"] == ("H-1B_DEPENDENT", "H_1B_DEPENDENT")
    assert all(len(v) == 1 for k, v in ALIASES.items() if k != "h1b_dependent")
    assert len(ALIASES) == 30  # the lca_cases columns, unchanged


@pytest.mark.parametrize("writer,suffix", [(write_csv, ".csv"), (write_xlsx, ".xlsx")])
@pytest.mark.parametrize("header", ["H-1B_DEPENDENT", "H_1B_DEPENDENT"])
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_either_spelling_loads_the_h1b_flag(db, tmp_path, writer, suffix, header):
    rows = [
        spelled(case("H-1", **{"H-1B_DEPENDENT": "Yes"}), header),
        spelled(case("H-2", **{"H-1B_DEPENDENT": "No"}), header),
    ]
    result = load_file(writer(tmp_path / f"h{suffix}", rows), 2026, database_url=TEST_DB_URL)
    assert result.missing_columns == [] and not result.bad_cells
    with db.connect() as conn:
        flags = dict(conn.execute(text("select case_number, h1b_dependent from lca_cases")).all())
    assert flags == {"H-1": True, "H-2": False}
    dumped = _all_text(db)
    for value in PERSONAL.values():  # the personal-data firewall still holds
        assert value not in dumped


@pytest.mark.parametrize("writer,suffix", [(write_csv, ".csv"), (write_xlsx, ".xlsx")])
def test_two_spellings_of_one_column_are_refused(tmp_path, writer, suffix):
    row = {**case("A-1"), "H_1B_DEPENDENT": "Yes"}  # both H-1B_DEPENDENT and H_1B_DEPENDENT
    path = writer(tmp_path / f"both{suffix}", [row])
    with pytest.raises(AmbiguousColumnsError, match="'H-1B_DEPENDENT' and 'H_1B_DEPENDENT'"):
        load_file(path, 2026, dry_run=True)


def test_missing_columns_name_the_column_and_every_header_tried(tmp_path):
    path = write_csv(tmp_path / "none.csv", [spelled(case("M-1"), "")])
    result = load_file(path, 2026, dry_run=True)
    assert result.missing_columns == ["h1b_dependent"]
    assert "h1b_dependent (H-1B_DEPENDENT, H_1B_DEPENDENT)" in summarize(result, dry_run=True)

    no_case = [{k: v for k, v in case("M-2").items() if k != "CASE_NUMBER"}]
    with pytest.raises(MissingColumnsError, match=r"case_number \(CASE_NUMBER\)"):
        load_file(write_csv(tmp_path / "nocase.csv", no_case), 2026, dry_run=True)


# --------------------------------------------------------------------- #
# N/A in flag columns: "not applicable", counted apart from bad cells


@pytest.mark.parametrize("writer,suffix", [(write_csv, ".csv"), (write_xlsx, ".xlsx")])
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_na_flags_load_as_null_and_are_not_bad_cells(db, tmp_path, writer, suffix):
    values = {"N-1": "Yes", "N-2": "No", "N-3": "N/A", "N-4": ""}
    rows = [
        spelled(
            case(
                n,
                **{"H-1B_DEPENDENT": v},
                WILLFUL_VIOLATOR=v,
                FULL_TIME_POSITION="N/A" if n == "N-3" else "Y",
            ),
            "H_1B_DEPENDENT",
        )
        for n, v in values.items()
    ]
    result = load_file(writer(tmp_path / f"na{suffix}", rows), 2026, database_url=TEST_DB_URL)
    assert result.bad_cells == {}
    assert result.not_applicable == {
        "h1b_dependent": 1,
        "willful_violator": 1,
        "full_time_position": 1,
    }
    assert "flags marked N/A (not applicable), loaded as NULL: " in summarize(result, dry_run=False)
    with db.connect() as conn:
        got = {
            r.case_number: (r.h1b_dependent, r.willful_violator, r.full_time_position)
            for r in conn.execute(
                text(
                    "select case_number, h1b_dependent, willful_violator, full_time_position from lca_cases"
                )
            )
        }
    assert got == {
        "N-1": (True, True, True),
        "N-2": (False, False, True),
        "N-3": (None, None, None),
        "N-4": (None, None, True),
    }


def test_na_only_input_has_no_bad_cells(tmp_path):
    rows = [
        case(f"Z-{i}", **{"H-1B_DEPENDENT": na}, WILLFUL_VIOLATOR=na, FULL_TIME_POSITION=na)
        for i, na in enumerate(["N/A", "NA", "n/a"])
    ]
    result = load_file(write_csv(tmp_path / "na_only.csv", rows), 2026, dry_run=True)
    assert result.bad_cells == {}
    assert result.not_applicable == {
        "h1b_dependent": 3,
        "willful_violator": 3,
        "full_time_position": 3,
    }


# --------------------------------------------------------------------- #
# coverage: which months a file covers, and cases outside its fiscal year


def test_fiscal_year_bounds_are_the_federal_fiscal_year():
    assert fiscal_year_bounds(2026) == (date(2025, 10, 1), date(2026, 9, 30))


def decided(n: str, when: str) -> dict:
    return case(n, DECISION_DATE=when)


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_coverage_of_two_quarterly_files_and_v_lca_coverage(db, tmp_path):
    # FY2026 Q1 holds one quarter; Q2 repeats one Q1 case and adds Q2's
    q1 = write_xlsx(
        tmp_path / "LCA_FY2026_Q1.xlsx",
        [decided("C-1", "10/15/2025"), decided("C-2", "11/20/2025"), decided("C-3", "12/05/2025")],
    )
    q2 = write_csv(
        tmp_path / "LCA_FY2026_Q2.csv",
        [
            decided("C-3", "12/05/2025"),
            decided("C-4", "2026-01-10"),
            decided("C-5", "02/14/2026"),
            decided("C-6", "03/31/2026"),
            decided("C-7", ""),  # no decision date: a case, but no month
        ],
    )
    fy2025 = write_csv(
        tmp_path / "LCA_FY2025_Q4.csv",
        [decided("P-1", "08/15/2025"), decided("P-2", "09/30/2025")],
    )
    r1 = load_file(q1, 2026, database_url=TEST_DB_URL)
    r2 = load_file(q2, 2026, database_url=TEST_DB_URL)
    load_file(fy2025, 2025, database_url=TEST_DB_URL)

    assert (r1.decision_date_min, r1.decision_date_max) == (date(2025, 10, 15), date(2025, 12, 5))
    assert r1.by_decision_month == {"2025-10": 1, "2025-11": 1, "2025-12": 1}
    assert (r1.no_decision_date, r1.outside_fiscal_year) == (0, 0)
    assert (r2.decision_date_min, r2.decision_date_max) == (date(2025, 12, 5), date(2026, 3, 31))
    assert r2.by_decision_month == {"2025-12": 1, "2026-01": 1, "2026-02": 1, "2026-03": 1}
    assert (r2.no_decision_date, r2.outside_fiscal_year) == (1, 0)

    out = summarize(r1, dry_run=False)
    assert "FY2026 runs 2025-10-01 to 2026-09-30" in out
    assert "DECISION_DATE coverage: 2025-10-15 to 2025-12-05" in out
    assert "  2025-10  1\n  2025-11  1\n  2025-12  1" in out
    assert "decided outside FY2026: 0" in out and "WARNING" not in out

    apply_views(TEST_DB_URL)
    with db.connect() as conn:
        got = {
            r["fiscal_year"]: r
            for r in conn.execute(text("select * from v_lca_coverage")).mappings()
        }
    assert {fy: dict(r) for fy, r in got.items()} == {
        2026: {
            "fiscal_year": 2026,
            "n_cases": 7,  # C-3 is in both files, stored once
            "min_decision_date": date(2025, 10, 15),
            "max_decision_date": date(2026, 3, 31),
            "n_months_with_decisions": 6,
        },
        2025: {
            "fiscal_year": 2025,
            "n_cases": 2,
            "min_decision_date": date(2025, 8, 15),
            "max_decision_date": date(2025, 9, 30),
            "n_months_with_decisions": 2,
        },
    }


def test_months_with_no_decisions_show_as_zero(tmp_path):
    path = write_csv(
        tmp_path / "gap.csv", [decided("G-1", "10/01/2025"), decided("G-2", "12/31/2025")]
    )
    out = summarize(load_file(path, 2026, dry_run=True), dry_run=True)
    assert "  2025-10  1\n  2025-11  0\n  2025-12  1" in out


def test_no_decision_dates_still_summarize(tmp_path):
    path = write_csv(tmp_path / "nodates.csv", [decided("E-1", "")])
    result = load_file(path, 2026, dry_run=True)
    assert result.decision_date_min is None and result.no_decision_date == 1
    assert "DECISION_DATE coverage: no decision dates" in summarize(result, dry_run=True)


def test_up_to_one_percent_outside_the_fiscal_year_warns_but_loads(tmp_path, caplog):
    # the FY's first and last days are inside it; one case of 100 is outside
    rows = [decided("F-0", "10/01/2025"), decided("F-1", "09/30/2026")]
    rows += [decided(f"F-{i}", "01/15/2026") for i in range(2, 99)]
    rows += [decided("F-99", "09/30/2025")]
    with caplog.at_level(logging.WARNING, logger="src.visa.lca_loader"):
        result = load_file(write_csv(tmp_path / "one.csv", rows), 2026, dry_run=True)
    assert (result.rows_loaded, result.outside_fiscal_year) == (100, 1)
    assert "1 of 100 cases (1.0%) were decided outside FY2026" in caplog.text
    assert "decided outside FY2026: 1  <-- WARNING" in summarize(result, dry_run=True)


def test_more_than_one_percent_outside_is_refused_in_a_dry_run_too(tmp_path):
    rows = [decided(f"F-{i}", "01/15/2026") for i in range(98)]
    rows += [decided("F-98", "09/30/2025"), decided("F-99", "10/01/2026")]
    path = write_csv(tmp_path / "two.csv", rows)
    with pytest.raises(OutsideFiscalYearError, match=r"2 of 100 cases \(2\.0%\)") as err:
        load_file(path, 2026, dry_run=True)
    assert err.value.result.outside_fiscal_year == 2
    assert "REFUSED (nothing written)" in summarize(err.value.result, dry_run=True)


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_a_mislabelled_fiscal_year_writes_nothing_unless_allowed(db, tmp_path):
    path = write_csv(tmp_path / "LCA_FY2026_Q1.csv", [case("W-1"), case("W-2")])  # FY2026 cases
    with pytest.raises(OutsideFiscalYearError, match="--allow-outside-fy"):
        load_file(path, 2025, database_url=TEST_DB_URL)
    with db.connect() as conn:
        assert conn.execute(text("select count(*) from lca_cases")).scalar_one() == 0

    result = load_file(path, 2025, database_url=TEST_DB_URL, allow_outside_fy=True)
    assert (result.rows_loaded, result.outside_fiscal_year, result.refused) == (2, 2, "")
    with db.connect() as conn:
        assert conn.execute(text("select count(*) from lca_cases")).scalar_one() == 2


def test_cli_prints_coverage_and_exits_non_zero_when_refused(tmp_path, monkeypatch, capsys):
    path = write_csv(tmp_path / "LCA_FY2026_Q1.csv", [case("X-1")])
    argv = ["lca_loader", "--file", str(path), "--fiscal-year", "2025", "--dry-run"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_:
        main()
    assert str(exit_.value.code).startswith("refused: LCA_FY2026_Q1.csv: 1 of 1 cases")
    out = capsys.readouterr().out
    assert "DECISION_DATE coverage: 2025-11-10 to 2025-11-10" in out
    assert "decided outside FY2025: 1  <-- WARNING" in out

    monkeypatch.setattr(sys, "argv", [*argv, "--allow-outside-fy"])
    main()
    assert "cases parsed (dry run, nothing written): 1" in capsys.readouterr().out
