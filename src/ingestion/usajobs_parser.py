"""Parse raw USAJobs search-result dicts into normalized field dicts.

Pure functions only — no I/O, no database. Every function here is
unit-tested against a fixture saved from a real API response in
`tests/fixtures/`.

USAJobs returns full, untruncated text (confirmed against a live
sample: `QualificationSummary` ranged 917-6170 chars across 25 results,
none truncated, no embedded HTML), unlike Adzuna's 500-char-capped
`description`. Full narrative text goes straight into
`description_full`; `description` gets the short `JobSummary` field.

Judgment calls made during Phase 2-prep recon (docs/usajobs_sample_response.json):

- `external_id` is `MatchedObjectId`, not `PositionID`. `PositionID`
  (e.g. "FD-2026-0027") is the hiring agency's own announcement number
  — human-readable but agency-assigned, not guaranteed unique across
  agencies. `MatchedObjectId` is USAJobs' own system key.
- `companies.canonical_name` = `DepartmentName` (cabinet-level agency),
  not `OrganizationName` (sub-component). Coarser but keeps the
  companies table from fragmenting into hundreds of internal office
  names. `OrganizationName` is not currently captured anywhere.
- `PositionLocation` is a list and can be large (359 locations seen for
  one "Nationwide" posting). Per the "flag, don't guess" principle,
  `parse_location` returns None whenever a posting has anything other
  than exactly one location, rather than arbitrarily picking the first.
- `description_full` concatenates only narrative fields (JobSummary,
  MajorDuties, Education, Requirements, QualificationSummary) —
  deliberately excludes application-process boilerplate (HowToApply,
  RequiredDocuments, Benefits, OtherInformation) that would dilute
  skill-extraction signal.
- Salary period and contract fields map only codes verified against
  USAJobs' own codelist API (`/api/codelist/remunerationrateintervalcodes`,
  `/api/codelist/positionscheduletypes`, `/api/codelist/positionofferingtypes`).
  Codes with no clean fit onto our existing enums resolve to None
  instead of being force-collapsed into a possibly-misleading bucket.
- `category` joins *every* `JobCategory` entry's label (semicolon-
  delimited, see `split_categories`), not just the first. Confirmed
  live that ~4% of postings carry more than one (interdisciplinary
  announcements) -- keeping only the first silently hid the second from
  anything filtering on category. See `src/cleaning/scope_classifier.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.ingestion.adzuna_parser import normalize_title

SOURCE = "usajobs"

# Verified via GET /api/codelist/remunerationrateintervalcodes. Codes with
# no clean fit onto our year/hour/month enum (BW Bi-weekly, FB Fee Basis,
# PD Per Day, PW Piece Work, ST Student Stipend, SY School Year,
# WC Without Compensation) are left unmapped -> salary_period None.
_RATE_INTERVAL_TO_PERIOD = {
    "PA": "year",
    "PH": "hour",
    "PM": "month",
}

# Verified via GET /api/codelist/positionscheduletypes. Shift work (3),
# Intermittent (4), Job sharing (5), and Multiple Schedules (6) don't map
# onto our full_time/part_time pair -> left unmapped.
_SCHEDULE_TO_CONTRACT_TIME = {
    "1": "full_time",
    "2": "part_time",
}

# Verified via GET /api/codelist/positionofferingtypes. Only "Permanent"
# maps cleanly onto Adzuna's contract_type vocabulary; collapsing the many
# other offering types (Temporary, Term, Seasonal, Internships, Telework,
# ...) into a binary permanent/contract split would misrepresent them.
_OFFERING_TO_CONTRACT_TYPE = {
    "15317": "permanent",
}

# Narrative fields concatenated into description_full, in display order.
# QualificationSummary lives at the MatchedObjectDescriptor level, not
# under UserArea.Details, unlike the others.
_NARRATIVE_DETAIL_FIELDS = ("JobSummary", "MajorDuties", "Education", "Requirements")


def parse_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one USAJobs search-result item onto `jobs` table fields.

    Returns a dict of column -> value. Raises KeyError only if the
    result has no `MatchedObjectId` — everything else degrades to None.
    """
    external_id = str(raw["MatchedObjectId"])  # required; unusable without it
    mod = raw.get("MatchedObjectDescriptor") or {}
    title = (mod.get("PositionTitle") or "").strip() or "(untitled)"

    description, description_full = _parse_descriptions(mod)
    salary_min, salary_max, salary_currency, salary_period = _parse_salary(mod)

    return {
        "external_id": external_id,
        "source": SOURCE,
        "title": title,
        "title_normalized": normalize_title(title),
        "description": description,
        "description_full": description_full,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_period": salary_period,
        # USAJobs salaries are employer-disclosed pay bands, never a
        # modeled estimate -- unlike Adzuna's salary_is_predicted.
        "salary_is_predicted": False,
        "is_remote": _parse_remote(mod),
        "category": _parse_category(mod),
        "contract_type": _parse_contract_type(mod),
        "contract_time": _parse_contract_time(mod),
        "redirect_url": mod.get("PositionURI"),
        "posted_at": parse_published(mod.get("PublicationStartDate")),
    }


def parse_company(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Extract company fields; None when the posting has no department.

    Uses `DepartmentName` (cabinet-level agency), not `OrganizationName`
    (sub-component) -- see module docstring.
    """
    mod = raw.get("MatchedObjectDescriptor") or {}
    department = (mod.get("DepartmentName") or "").strip()
    if not department:
        return None
    return {"canonical_name": department, "raw_names": [department]}


def parse_location(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Extract location fields from `PositionLocation`.

    None when the posting has zero locations or more than one -- a
    single FK can't honestly represent a multi-location (sometimes
    hundreds) posting without guessing which one matters.
    """
    mod = raw.get("MatchedObjectDescriptor") or {}
    locations = mod.get("PositionLocation") or []
    if len(locations) != 1:
        return None
    loc = locations[0]
    # USAJobs' field names are misleading: CountryCode holds the full
    # country name ("United States"), CountrySubDivisionCode the full
    # state name ("Maryland") -- neither is actually a code. Stored
    # as-is (Phase 1/2-prep philosophy: store what the source gives,
    # don't normalize across sources yet).
    country = loc.get("CountryCode")
    state = loc.get("CountrySubDivisionCode")
    city = _extract_city(loc.get("CityName") or loc.get("LocationName"), state)
    return {
        "country": country,
        "state": state,
        "city": city,
        "is_remote": _parse_remote(mod),
        "latitude": loc.get("Latitude"),
        "longitude": loc.get("Longitude"),
    }


# --------------------------------------------------------------------- #
# helpers


def _extract_city(city_name: str | None, state: str | None) -> str | None:
    """USAJobs' CityName is observed to duplicate LocationName as
    "City, State" rather than a bare city -- strip the state suffix."""
    city_name = (city_name or "").strip()
    if not city_name:
        return None
    if state and city_name.endswith(f", {state}"):
        city_name = city_name[: -(len(state) + 2)]
    elif "," in city_name:
        city_name = city_name.rsplit(",", 1)[0]
    city_name = city_name.strip()
    return city_name or None


def _parse_descriptions(mod: dict[str, Any]) -> tuple[str | None, str | None]:
    details = mod.get("UserArea", {}).get("Details") or {}

    job_summary = (details.get("JobSummary") or "").strip()

    major_duties = details.get("MajorDuties")
    if isinstance(major_duties, list):
        major_duties_text = "\n\n".join(d.strip() for d in major_duties if d and d.strip())
    else:
        major_duties_text = (major_duties or "").strip()

    education = (details.get("Education") or "").strip()
    requirements = (details.get("Requirements") or "").strip()
    qualification_summary = (mod.get("QualificationSummary") or "").strip()

    sections = [job_summary, major_duties_text, education, requirements, qualification_summary]
    full_text = "\n\n".join(s for s in sections if s)

    return (job_summary or None), (full_text or None)


def _parse_salary(mod: dict[str, Any]) -> tuple[int | None, int | None, str | None, str | None]:
    remuneration = mod.get("PositionRemuneration") or []
    if not remuneration:
        return None, None, None, None
    entry = remuneration[0]
    salary_min = _to_int(entry.get("MinimumRange"))
    salary_max = _to_int(entry.get("MaximumRange"))
    if salary_min is None and salary_max is None:
        return None, None, None, None
    period = _RATE_INTERVAL_TO_PERIOD.get(entry.get("RateIntervalCode"))
    return salary_min, salary_max, "USD", period


def _parse_remote(mod: dict[str, Any]) -> bool:
    details = mod.get("UserArea", {}).get("Details") or {}
    return bool(details.get("RemoteIndicator"))


_CATEGORY_DELIMITER = "; "


def _parse_category(mod: dict[str, Any]) -> str | None:
    """Join every JobCategory entry's label (falling back to Code per
    entry when its Name is blank) -- a posting can carry more than one
    (confirmed live: ~4% of a real sample), e.g. an "INTERDISCIPLINARY
    GENERAL ENGINEER/OPERATIONS RESEARCH ANALYST" tagged both General
    Engineering and Operations Research. Keeping only the first would
    silently hide the second from anything filtering on category
    (see scope_classifier.py)."""
    categories = mod.get("JobCategory") or []
    labels = []
    for cat in categories:
        label = (cat.get("Name") or "").strip() or cat.get("Code")
        if label and label not in labels:
            labels.append(label)
    return _CATEGORY_DELIMITER.join(labels) or None


def split_categories(category: str | None) -> list[str]:
    """Inverse of the joining in `_parse_category` -- for consumers
    (e.g. scope_classifier.py) that need to check membership per label
    rather than treat `jobs.category` as a single opaque string."""
    if not category:
        return []
    return category.split(_CATEGORY_DELIMITER)


def _parse_contract_time(mod: dict[str, Any]) -> str | None:
    schedules = mod.get("PositionSchedule") or []
    if not schedules:
        return None
    return _SCHEDULE_TO_CONTRACT_TIME.get(schedules[0].get("Code"))


def _parse_contract_type(mod: dict[str, Any]) -> str | None:
    offerings = mod.get("PositionOfferingType") or []
    if not offerings:
        return None
    return _OFFERING_TO_CONTRACT_TYPE.get(offerings[0].get("Code"))


def parse_published(value: str | None) -> datetime | None:
    """USAJobs `PublicationStartDate`, e.g. '2026-08-14T11:17:15.9170'.

    No timezone offset given; treated as UTC, matching
    `adzuna_parser.parse_created`'s handling of naive timestamps.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
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
