"""`job_snapshots` — daily observed state per job.

Included in Phase 1 deliberately (a deviation from the original v1
scope, agreed during planning): snapshot-driven *analysis* is Phase 3,
but the 90-day accumulation target can only be met if capture starts on
day one. One extra upsert per job per day; the analysis waits, the data
can't.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class JobSnapshot(Base):
    __tablename__ = "job_snapshots"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<JobSnapshot job_id={self.job_id} date={self.snapshot_date} active={self.is_active}>"
        )
