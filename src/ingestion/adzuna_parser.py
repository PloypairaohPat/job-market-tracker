"""Parse raw Adzuna job dicts into normalized field dicts.

Pure functions only — no I/O, no database. Every function here is
unit-tested against fixture data in `tests/fixtures/`.

Phase 1 parsing philosophy (see PROJECT_GUIDE.md):
- store as-is, don't normalize: company names are exact API strings
- flag rather than discard: missing/odd values become None, never guesses
- `title_normalized` is *only* lowercase + whitespace-collapse in Phase 1;
  real normalization (seniority, role clustering) is Phase 2
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

SOURCE = "adzuna"

# Simple, conservative remote signal for Phase 1. Phase 2 replaces this
# with description-level analysis; over-matching here is worse than
# under-matching because it silently corrupts the geography analysis.
_REMOTE_TITLE_RE = re.compile(r"\bremote\b", re.IGNORECASE)


def parse_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Adzuna result dict onto `jobs` table fields.

    Returns a dict of column -> value. Raises KeyError only if the
    posting has no `id` — everything else degrades to None.
    """
    external_id = str(raw["id"])  # required; a posting without an ID is unusable
    title = (raw.get("title") or "").strip() or "(untitled)"

    return {
        "external_id": external_id,
        "source": SOURCE,
        "title": title,
        "title_normalized": normalize_title(title),
        "description": raw.get("description"),
        "salary_min": _to_int(raw.get("salary_min")),
        "salary_max": _to_int(raw.get("salary_max")),
        # Adzuna US search returns annual USD figures; recorded explicitly
        # rather than assumed downstream. Revisit if non-US countries added.
        "salary_currency": "USD" if raw.get("salary_min") or raw.get("salary_max") else None,
        "salary_period": "year" if raw.get("salary_min") or raw.get("salary_max") else None,
        "salary_is_predicted": _parse_predicted(raw.get("salary_is_predicted")),
        "is_remote": detect_remote(raw),
        "category": (raw.get("category") or {}).get("label"),
        "contract_type": raw.get("contract_type"),
        "contract_time": raw.get("contract_time"),
        "redirect_url": raw.get("redirect_url"),
        "posted_at": parse_created(raw.get("created")),
    }


def parse_company(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Extract company fields; None when the posting has no company."""
    display_name = ((raw.get("company") or {}).get("display_name") or "").strip()
    if not display_name:
        return None
    return {"canonical_name": display_name, "raw_names": [display_name]}


def parse_location(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Extract location fields from Adzuna's `location.area` array.

    Adzuna's `area` is hierarchical, broadest first, e.g.
    ["US", "New York", "New York County", "New York"]. We take:
      country = area[0], state = area[1], city = area[-1] (if deeper).
    Anything the array doesn't provide is None — no guessing.
    """
    loc = raw.get("location") or {}
    area = [a for a in (loc.get("area") or []) if a]
    if not area:
        return None
    country = area[0]
    state = area[1] if len(area) > 1 else None
    city = area[-1] if len(area) > 2 else None
    return {
        "country": country,
        "state": state,
        "city": city,
        "is_remote": detect_remote(raw),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
    }


# --------------------------------------------------------------------- #
# helpers


def normalize_title(title: str) -> str:
    """Lowercase and collapse whitespace. Nothing more in Phase 1."""
    return re.sub(r"\s+", " ", title).strip().lower()


def detect_remote(raw: dict[str, Any]) -> bool:
    """Conservative Phase 1 remote signal: the word 'remote' in the title
    or in the location display name."""
    title = raw.get("title") or ""
    loc_display = (raw.get("location") or {}).get("display_name") or ""
    return bool(_REMOTE_TITLE_RE.search(title) or _REMOTE_TITLE_RE.search(loc_display))


def parse_created(value: str | None) -> datetime | None:
    """Adzuna `created` is ISO-8601, e.g. '2026-06-28T04:12:33Z'."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _parse_predicted(value: Any) -> bool | None:
    """Adzuna sends salary_is_predicted as the strings '0'/'1'."""
    if value is None:
        return None
    return str(value).strip() in {"1", "true", "True"}
