"""`skills` and `job_skills` — skill taxonomy and job-to-skill links.

The taxonomy itself is curated in `src/cleaning/data/skills.json` and
synced into the database by the extraction pipeline; the database rows
are a materialization, the JSON file is the source of truth (reviewable
in diffs, portable across environments).
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # 'Python', 'SQL'
    category: Mapped[str] = mapped_column(Text, nullable=False)  # 'language' | 'bi_tool' | ...
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Skill id={self.id} name={self.name!r} category={self.category!r}>"


class JobSkill(Base):
    __tablename__ = "job_skills"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)  # 0.00–1.00

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobSkill job_id={self.job_id} skill_id={self.skill_id} conf={self.confidence}>"
