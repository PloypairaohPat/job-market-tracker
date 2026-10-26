"""Integration tests for v_employer_sponsorship on synthetic lca_cases rows."""

import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.utils.db import session_scope
from tests.conftest import reset_schema
from tests.visa_helpers import insert_lca, lca

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    apply_views(TEST_DB_URL)
    with session_scope(TEST_DB_URL) as session:
        insert_lca(
            session,
            [
                # FY2026 -- counted: certified H-1B
                lca(
                    pw_wage_level="II", wage_rate_of_pay_from=Decimal("40"), wage_unit_of_pay="Hour"
                ),
                lca(
                    soc_code="15-1252.00",  # software developer: not analytics SOC
                    new_employment=0,
                    continued_employment=1,
                    pw_wage_level="IV",
                    wage_rate_of_pay_from=Decimal("9000"),
                    wage_unit_of_pay="Month",
                ),
                lca(
                    new_employment=2,
                    pw_wage_level="I",
                    wage_rate_of_pay_from=Decimal("1500"),
                    wage_unit_of_pay="Week",
                    h1b_dependent=True,
                ),
                lca(
                    pw_wage_level="III",
                    wage_rate_of_pay_from=Decimal("100000"),
                    wage_unit_of_pay="Piece Rate",  # unconvertible -> NULL, counted
                ),
                # FY2026 -- excluded by status / visa class
                lca(case_status="Certified-Withdrawn"),
                lca(case_status="Denied"),
                lca(visa_class="E-3 Australian"),
                # FY2024 -- inside the 3-FY window (2024..2026)
                lca(
                    fiscal_year=2024,
                    pw_wage_level="IV",
                    wage_rate_of_pay_from=Decimal("3500"),
                    wage_unit_of_pay="Bi-Weekly",
                ),
                # FY2023 -- outside the window
                lca(fiscal_year=2023, wage_rate_of_pay_from=Decimal("120000")),
                # a second employer with only treaty-visa filings
                lca("FAKE Treaty Visa Corp", visa_class="H-1B1 Chile"),
            ],
        )
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def _row(engine, key: str, period: str) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("select * from v_employer_sponsorship where employer_key=:k and period=:p"),
                {"k": key, "p": period},
            )
            .mappings()
            .one()
        )


def test_status_and_visa_class_filtering_and_analytics_subset(db):
    fy = _row(db, "fakeco analytics", "FY2026")
    assert fy["n_lcas_all_statuses"] == 7
    assert fy["certified_h1b_lcas"] == 4  # excludes Certified-Withdrawn, Denied, E-3
    assert fy["certified_h1b_new_employment"] == 3  # the continued-employment filing drops out
    assert fy["certified_h1b_analytics_soc"] == 3  # 15-1252 drops out
    assert fy["certified_h1b_analytics_soc_new_employment"] == 3
    assert (fy["wage_level_i"], fy["wage_level_ii"], fy["wage_level_iii"], fy["wage_level_iv"]) == (
        1,
        1,
        1,
        1,
    )
    assert fy["any_h1b_dependent"] is True
    assert fy["any_willful_violator"] is False

    treaty = _row(db, "fake treaty visa", "FY2026")
    assert treaty["n_lcas_all_statuses"] == 1
    assert treaty["certified_h1b_lcas"] == 0


def test_wage_conversion_and_unconvertible_units(db):
    fy = _row(db, "fakeco analytics", "FY2026")
    # 40/h * 2080 = 83,200; 9,000/mo * 12 = 108,000; 1,500/wk * 52 = 78,000;
    # 'Piece Rate' -> NULL (counted). Median of the three = 83,200.
    assert fy["median_offered_annual_wage"] == pytest.approx(83200)
    assert fy["n_wage_unit_unconvertible"] == 1


def test_three_fiscal_year_window(db):
    win = _row(db, "fakeco analytics", "last_3_fy")
    assert (win["window_start_fy"], win["window_end_fy"]) == (2024, 2026)
    assert win["period_fy"] is None
    assert win["certified_h1b_lcas"] == 5  # FY2026's 4 + FY2024's 1; FY2023 excluded
    # + 3,500 bi-weekly * 26 = 91,000 -> median of 78,000/83,200/91,000/108,000
    assert win["median_offered_annual_wage"] == pytest.approx(87100)

    old = _row(db, "fakeco analytics", "FY2023")
    assert old["certified_h1b_lcas"] == 1
