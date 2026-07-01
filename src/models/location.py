"""`locations` — normalized location entity.

Uniqueness is on the (city, state, country) triple. `metro_area`
assignment and remote-signal refinement are Phase 2 concerns; Phase 1
stores what the API provides.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    metro_area: Mapped[str | None] = mapped_column(Text)  # assigned in Phase 2
    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    __table_args__ = (
        UniqueConstraint("city", "state", "country", name="uq_locations_city_state_country"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Location id={self.id} city={self.city!r} state={self.state!r}>"
