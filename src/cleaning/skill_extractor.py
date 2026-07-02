"""High-precision skill extraction from job description text.

Phase 2 strategy (per PROJECT_GUIDE.md risk table): start with
regex-based extraction for a curated taxonomy — high precision, easily
audited — and layer spaCy patterns on top later, *after* a manually
audited baseline exists to measure them against.

Design notes:
- The taxonomy (src/cleaning/data/skills.json) is the source of truth;
  this module compiles it into matchers. Adding a skill is a data
  change, not a code change.
- Boundaries use lookarounds `(?<![\\w])...(?![\\w])` rather than `\\b`
  so terms containing spaces or symbols ("Power BI", "A/B Testing",
  "scikit-learn") anchor correctly at both ends.
- Ambiguous terms (R, SAS, Excel, Spark, dbt, ...) carry case-sensitive
  or context-anchored patterns and reduced confidence — precision over
  recall, always. A missed mention costs a little recall; a false
  positive silently corrupts every downstream skill analysis.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TAXONOMY_PATH = Path(__file__).parent / "data" / "skills.json"

VALID_CATEGORIES = {
    "language",
    "database",
    "bi_tool",
    "data_tool",
    "cloud",
    "ml_stats",
    "workflow",
    "soft",
}


@dataclass(frozen=True)
class SkillDef:
    name: str
    category: str
    confidence: float
    regex: re.Pattern


def _default_pattern(terms: list[str]) -> str:
    """Alternation over name + aliases with lookaround boundaries."""
    escaped = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return r"(?<![\w])(?:" + "|".join(escaped) + r")(?![\w])"


def load_taxonomy(path: Path = TAXONOMY_PATH) -> list[SkillDef]:
    """Load and compile the taxonomy. Raises on malformed entries —
    a broken taxonomy should fail loudly at startup, not mis-extract."""
    raw = json.loads(path.read_text())
    defs: list[SkillDef] = []
    seen: set[str] = set()
    for entry in raw["skills"]:
        name = entry["name"]
        if name in seen:
            raise ValueError(f"Duplicate skill name in taxonomy: {name!r}")
        seen.add(name)
        category = entry["category"]
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Skill {name!r} has invalid category {category!r}")
        pattern = entry.get("pattern") or _default_pattern([name, *entry.get("aliases", [])])
        flags = 0 if entry.get("case_sensitive", False) else re.IGNORECASE
        defs.append(
            SkillDef(
                name=name,
                category=category,
                confidence=float(entry.get("confidence", 1.0)),
                regex=re.compile(pattern, flags),
            )
        )
    return defs


@lru_cache(maxsize=1)
def _cached_taxonomy() -> tuple[SkillDef, ...]:
    return tuple(load_taxonomy())


class SkillExtractor:
    """Extract taxonomy skills from free text."""

    def __init__(self, taxonomy: list[SkillDef] | None = None) -> None:
        self.taxonomy = list(taxonomy) if taxonomy is not None else list(_cached_taxonomy())

    def extract(self, text: str | None) -> dict[str, float]:
        """Return {canonical_skill_name: confidence} for skills found.

        Aliases resolve to the canonical name, so 'Postgres' and
        'PostgreSQL' in the same text produce one entry.
        """
        if not text:
            return {}
        found: dict[str, float] = {}
        for skill in self.taxonomy:
            if skill.regex.search(text):
                found[skill.name] = skill.confidence
        return found
