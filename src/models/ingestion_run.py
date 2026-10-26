"""`ingestion_runs` — one row per ingestion run per source.

The clock's evidence: which runs happened, how they ended, and how many
API calls they spent (the monthly Adzuna budget is billed against
`calls_made`, see src/ingestion/budget.py). Written by
src/ingestion/run_log.py: a row opens as `running` and is always closed
with a final status, exceptions included. Dry runs write no row.

`params` records what was asked for (queries, series codes, max_pages,
max_calls, dry_run) and never credentials; `error` is redacted and capped
at 2,000 characters.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # adzuna | usajobs
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = running
    # running | ok | partial | failed | skipped_budget
    status: Mapped[str] = mapped_column(Text, nullable=False)
    calls_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_date: Mapped[date | None] = mapped_column(Date)  # UTC date of the run
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_ingestion_runs_source_started_at", "source", "started_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IngestionRun id={self.id} source={self.source!r} status={self.status!r}>"
