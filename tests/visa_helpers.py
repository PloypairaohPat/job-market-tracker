"""Synthetic-data helpers shared by the visa-layer tests. All values invented."""

from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.cleaning.company_normalizer import normalize_company_name
from src.models import LcaCase

_counter = iter(range(1, 1_000_000))


def lca(employer: str = "FAKECO Analytics LLC", **overrides) -> dict:
    """One lca_cases row: a certified analytics-SOC H-1B new hire unless overridden."""
    row = {
        "case_number": f"I-FAKE-{next(_counter):06d}",
        "case_status": "Certified",
        "visa_class": "H-1B",
        "soc_code": "15-2051.01",
        "new_employment": 1,
        "continued_employment": 0,
        "pw_wage_level": "II",
        "wage_rate_of_pay_from": Decimal("90000"),
        "wage_unit_of_pay": "Year",
        "h1b_dependent": False,
        "willful_violator": False,
        "employer_name": employer,
        "employer_key": normalize_company_name(employer),
        "fiscal_year": 2026,
        "source_file": "synthetic.csv",
    }
    row.update(overrides)
    return row


def insert_lca(session, rows: list[dict]) -> None:
    session.execute(pg_insert(LcaCase).values(rows))
