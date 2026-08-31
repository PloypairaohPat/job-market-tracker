"""Relevance classification — is a posting actually a data-analytics role?

Phase 2-prep problem (backed by real ingested data, see data_dictionary.md):
federal keyword search is badly polluted. "analyst" matches Budget
Analysts, Intelligence Specialists, Procurement Analysts, Accountants,
Engineers — of 183 USAJobs postings ingested by keyword, only ~10-25
are genuinely data-analytics roles. Skill statistics computed over the
whole population are meaningless.

Policy: **flag, never delete.** Every job keeps its row; `in_scope` and
`scope_reason` are set so the filter is auditable and revisitable
(`WHERE in_scope` in analyses), exactly like `salary_quality`.

Source-agnostic by design, but only USAJobs currently needs real
classification logic:
- Adzuna (and any other non-USAJobs source): always `in_scope=True`.
  Commercial keyword search is far less polluted than federal series
  codes — reconsider only if real data says otherwise.
- USAJobs: category-based, using the real category distribution from
  183 live-ingested postings (see data_dictionary.md):
    - A small set of series is unambiguously quantitative/analytics
      (Data Science Series, Operations Research, Statistics) -> in scope.
    - Two series are genuinely ambiguous catch-alls (Management And
      Program Analysis, Information Technology Management) -> tie-broken
      by skill density: >=2 distinct skills from the language/database/
      bi_tool/data_tool/ml_stats taxonomy categories, found in the job's
      text. This threshold was validated against the real 66-job
      Management-And-Program-Analysis bucket: >=2 yields 14 in-scope
      (titles like "Data Analyst" and "Program Analyst (Informatics)"
      correctly pass; generic "MANAGEMENT ANALYST" correctly fails) —
      combined with Operations Research's clean 9, that lands at 23/183,
      matching the independently-estimated ~10-25 range.
    - Everything else (Budget Analysis, Intelligence, General
      Engineering, ...) -> out of scope by default. A posting with no
      category at all -> out of scope (no signal to include it on).
    - `category` can hold multiple semicolon-joined labels (see
      `usajobs_parser.split_categories`) — a posting counts as in-scope
      if *any* of its labels qualifies, not just the first (this is
      exactly the case for job 865002200, "INTERDISCIPLINARY GENERAL
      ENGINEER/OPERATIONS RESEARCH ANALYST", tagged both General
      Engineering and Operations Research).
"""

from __future__ import annotations

from src.cleaning.skill_extractor import SkillExtractor
from src.ingestion.usajobs_parser import split_categories

USAJOBS_SOURCE = "usajobs"

# Verified against the real occupational-series codelist
# (GET /api/codelist/occupationalseries) and the live ingested category
# distribution — see data_dictionary.md.
CLEAN_IN_SCOPE_CATEGORIES = frozenset(
    {
        "Data Science Series",
        "Operations Research",
        "Statistics",
    }
)

# Genuinely ambiguous catch-all series -- tie-broken by skill density
# rather than included or excluded outright.
AMBIGUOUS_CATEGORIES = frozenset(
    {
        "Management And Program Analysis",
        "Information Technology Management",
    }
)

# Skill taxonomy categories treated as analytics signal for the tie-break.
# Excludes 'cloud', 'workflow', 'soft' -- weaker standalone signals for
# "is this an analytics role" than a language/tool/stats mention.
ANALYTICS_SKILL_CATEGORIES = frozenset({"language", "database", "bi_tool", "data_tool", "ml_stats"})

# Empirically validated against the real 66-job Management-And-Program-
# Analysis bucket -- see module docstring.
SKILL_DENSITY_THRESHOLD = 2


def classify_scope(
    source: str,
    category: str | None,
    text: str,
    extractor: SkillExtractor,
) -> tuple[bool, str]:
    """Return (in_scope, reason). `text` is typically title + (description_full or description)."""
    if source != USAJOBS_SOURCE:
        return True, "non_usajobs_default"

    labels = split_categories(category)
    if not labels:
        return False, "no_category"

    for label in labels:
        if label in CLEAN_IN_SCOPE_CATEGORIES:
            return True, f"series:{label}"

    for label in labels:
        if label in AMBIGUOUS_CATEGORIES:
            n = _count_analytics_skills(text, extractor)
            if n >= SKILL_DENSITY_THRESHOLD:
                return True, f"skill_density:{label}:{n}"
            return False, f"skill_density:{label}:{n}"

    return False, f"category_excluded:{category}"


def _count_analytics_skills(text: str, extractor: SkillExtractor) -> int:
    found = extractor.extract(text)
    if not found:
        return 0
    by_name = {skill.name: skill.category for skill in extractor.taxonomy}
    return sum(1 for name in found if by_name.get(name) in ANALYTICS_SKILL_CATEGORIES)
