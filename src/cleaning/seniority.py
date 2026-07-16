"""Seniority classification from job titles.

Buckets: 'junior' | 'mid' | 'senior' | 'lead' | None.

Judgment calls (documented here and in the data dictionary):
- **None means unknown, not mid.** A bare "Data Analyst" title carries
  no seniority signal; forcing it into 'mid' would fabricate data.
- "Associate" is junior in most markets — EXCEPT "Associate Director" /
  "Associate Manager" style titles, which outrank senior.
- 'lead' absorbs lead/principal/staff/head/director/manager: people-
  leadership and top-IC titles are one bucket at this dataset's size.
- Roman numerals: I -> junior, II -> mid, III/IV -> senior.
- Precedence when multiple signals appear: lead > senior > mid > junior
  ("Senior Lead Analyst" is a lead).
"""

from __future__ import annotations

import re

_ASSOC_LEADER = re.compile(r"\bassociate\s+(director|manager|principal)\b", re.IGNORECASE)
_LEAD = re.compile(
    r"\b(lead|principal|staff|head|director|manager|mgr|vp|vice president)\b", re.IGNORECASE
)
_SENIOR = re.compile(r"\b(senior|sr\.?|iii|iv)\b", re.IGNORECASE)
_MID = re.compile(r"\b(ii|mid[- ]?level|intermediate)\b", re.IGNORECASE)
_JUNIOR = re.compile(
    r"\b(junior|jr\.?|entry[- ]?level|entry|intern(ship)?|graduate|trainee|associate|i)\b",
    re.IGNORECASE,
)


def classify_seniority(title: str | None) -> str | None:
    """Classify a raw job title into a seniority bucket, or None if no signal."""
    if not title:
        return None
    if _ASSOC_LEADER.search(title) or _LEAD.search(title):
        return "lead"
    if _SENIOR.search(title):
        return "senior"
    if _MID.search(title):
        return "mid"
    if _JUNIOR.search(title):
        return "junior"
    return None
