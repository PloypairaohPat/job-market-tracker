"""`raw_responses` — every API call result, stored verbatim.

This table is the project's insurance policy (the raw-then-normalized
pattern): schema changes and parsing bug fixes can be replayed against
historical responses without re-fetching from the API.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawResponse(Base):
    __tablename__ = "raw_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # 'adzuna' | 'usajobs' | ...
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_raw_responses_source_fetched_at", "source", "fetched_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RawResponse id={self.id} source={self.source!r} fetched_at={self.fetched_at}>"
