"""`companies` — normalized company entity.

Phase 1 intentionally does **no** deduplication: `canonical_name` is the
exact string from the API and `raw_names` records every variant seen.
Phase 2 builds normalization as a layer on top of this — never as a
destructive transform.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    raw_names: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    industry: Mapped[str | None] = mapped_column(Text)
    size_bucket: Mapped[str | None] = mapped_column(Text)  # '1-50' | '51-200' | ...
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company id={self.id} canonical_name={self.canonical_name!r}>"
