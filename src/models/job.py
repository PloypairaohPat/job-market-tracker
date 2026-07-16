"""`jobs` — one row per unique job posting.

Idempotency key: (source, external_id). Adzuna IDs are only guaranteed
unique *within* Adzuna, so the natural key includes the source — this
matters the moment USAJobs is added.

`first_seen_at` / `last_seen_at` give coarse lifecycle tracking from day
one; fine-grained daily state lives in `job_snapshots`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))

    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str | None] = mapped_column(Text)  # lowercased/trimmed only in Phase 1
    seniority: Mapped[str | None] = mapped_column(Text)  # classified in Phase 2
    description: Mapped[str | None] = mapped_column(Text)

    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(Text)
    salary_period: Mapped[str | None] = mapped_column(Text)  # 'year' | 'hour' | 'month'
    salary_is_predicted: Mapped[bool | None] = mapped_column(Boolean)  # Adzuna estimates flagged
    salary_quality: Mapped[str | None] = mapped_column(
        Text
    )  # None|ok|suspect_* — set by cleaning pipeline; see data dictionary

    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    category: Mapped[str | None] = mapped_column(Text)
    contract_type: Mapped[str | None] = mapped_column(Text)
    contract_time: Mapped[str | None] = mapped_column(Text)
    redirect_url: Mapped[str | None] = mapped_column(Text)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_response_id: Mapped[int | None] = mapped_column(ForeignKey("raw_responses.id"))

    company = relationship("Company")
    location = relationship("Location")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
        Index("ix_jobs_company_id", "company_id"),
        Index("ix_jobs_location_id", "location_id"),
        Index("ix_jobs_posted_at", "posted_at"),
        Index("ix_jobs_title_normalized", "title_normalized"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job id={self.id} source={self.source!r} external_id={self.external_id!r} title={self.title!r}>"
