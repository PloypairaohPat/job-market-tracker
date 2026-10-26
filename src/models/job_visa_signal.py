"""`job_visa_signals` — what each posting's own text says about visas.

One row per job, rebuilt wholesale by the `visa` step of
`python -m src.cleaning.apply_cleaning` from stored titles, descriptions,
company names and (for USAJobs) the raw response. A derived layer: it can
be dropped and recomputed at any time. Rules: src/visa/posting_signals.py.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class JobVisaSignal(Base):
    __tablename__ = "job_visa_signals"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    restriction: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # citizenship|clearance|none_found
    restriction_reason: Mapped[str | None] = mapped_column(Text)
    sponsorship_stance: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # will_not_sponsor | will_sponsor | none_found
    sponsorship_reason: Mapped[str | None] = mapped_column(Text)
    opt_mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    text_coverage: Mapped[str] = mapped_column(Text, nullable=False)  # full | truncated | empty
    cap_exempt_hint: Mapped[str] = mapped_column(Text, nullable=False)  # likely | unknown
    cap_exempt_reason: Mapped[str | None] = mapped_column(Text)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<JobVisaSignal job_id={self.job_id} restriction={self.restriction!r} "
            f"stance={self.sponsorship_stance!r}>"
        )
