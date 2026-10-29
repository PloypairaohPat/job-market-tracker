"""`lca_cases` — one row per Labor Condition Application from DOL's
public LCA disclosure files (Office of Foreign Labor Certification).

An LCA is a filing, not an approved H-1B and not a hire — see
docs/data_dictionary.md. Only an explicit column allowlist is loaded
(src/visa/lca_loader.py): the files also carry real people's names,
emails and phone numbers (employer contacts, attorneys, preparers),
and those columns never reach this table.

Keyed on `case_number`. Some fiscal years' quarterly files hold one
quarter each and others are cumulative; every quarterly file is loaded,
oldest first, and a case in two files is upserted, never double counted.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class LcaCase(Base):
    __tablename__ = "lca_cases"

    case_number: Mapped[str] = mapped_column(Text, primary_key=True)
    case_status: Mapped[str | None] = mapped_column(Text)  # Certified | Certified - Withdrawn | ...
    received_date: Mapped[date | None] = mapped_column(Date)
    decision_date: Mapped[date | None] = mapped_column(Date)
    visa_class: Mapped[str | None] = mapped_column(Text)  # H-1B | E-3 Australian | H-1B1 ...
    job_title: Mapped[str | None] = mapped_column(Text)
    soc_code: Mapped[str | None] = mapped_column(Text)
    soc_title: Mapped[str | None] = mapped_column(Text)
    full_time_position: Mapped[bool | None] = mapped_column(Boolean)
    begin_date: Mapped[date | None] = mapped_column(Date)
    total_worker_positions: Mapped[int | None] = mapped_column(Integer)
    new_employment: Mapped[int | None] = mapped_column(Integer)
    continued_employment: Mapped[int | None] = mapped_column(Integer)
    change_employer: Mapped[int | None] = mapped_column(Integer)
    employer_name: Mapped[str | None] = mapped_column(Text)
    trade_name_dba: Mapped[str | None] = mapped_column(Text)
    employer_city: Mapped[str | None] = mapped_column(Text)
    employer_state: Mapped[str | None] = mapped_column(Text)
    employer_fein: Mapped[str | None] = mapped_column(Text)
    naics_code: Mapped[str | None] = mapped_column(Text)
    worksite_city: Mapped[str | None] = mapped_column(Text)
    worksite_state: Mapped[str | None] = mapped_column(Text)
    wage_rate_of_pay_from: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    wage_rate_of_pay_to: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    wage_unit_of_pay: Mapped[str | None] = mapped_column(Text)  # Hour | Week | Bi-Weekly | ...
    prevailing_wage: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    pw_unit_of_pay: Mapped[str | None] = mapped_column(Text)
    pw_wage_level: Mapped[str | None] = mapped_column(Text)  # I | II | III | IV | N/A
    h1b_dependent: Mapped[bool | None] = mapped_column(Boolean)  # H_1B_DEPENDENT / H-1B_DEPENDENT
    willful_violator: Mapped[bool | None] = mapped_column(Boolean)

    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)  # basename of the loaded file
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # normalize_company_name(employer_name); recomputable grouping key
    employer_key: Mapped[str | None] = mapped_column(Text, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LcaCase {self.case_number} {self.case_status!r} {self.employer_name!r}>"
