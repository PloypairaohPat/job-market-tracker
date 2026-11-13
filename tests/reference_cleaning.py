"""E0: a frozen copy of the cleaning and skills code as it stood before Part E.

Copied from src/cleaning/apply_cleaning.py and
src/cleaning/extract_skills.py at the end of Part D (after A2 and A3, so
no behaviour difference is intended anywhere; only the stale-link log line
was dropped). The reference-equality test
(tests/test_cleaning_reference_equality.py) runs this and the production
code on the same seeded database and asserts identical contents. Never
"fix" this file to match production: it is the definition of the results
Part E's faster code must reproduce.

`apply_companies` is not copied: Part E leaves it untouched, and the test
runs the production version for both sides.
"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.cleaning.metro import assign_metro
from src.cleaning.remote import detect_remote
from src.cleaning.salary_quality import assess_salary_quality
from src.cleaning.scope_classifier import classify_scope
from src.cleaning.seniority import classify_seniority
from src.cleaning.skill_extractor import SkillExtractor
from src.models import Company, Job, JobSkill, JobVisaSignal, Location, RawResponse
from src.visa.posting_signals import classify_posting

REFERENCE_BATCH_SIZE = 500


def apply_seniority(session: Session) -> dict[str, int]:
    dist: dict[str, int] = {}
    for job in session.execute(select(Job)).scalars():
        job.seniority = classify_seniority(job.title)
        key = job.seniority or "(none)"
        dist[key] = dist.get(key, 0) + 1
    return dist


def apply_salary_quality(session: Session) -> dict[str, int]:
    dist: dict[str, int] = {}
    for job in session.execute(select(Job)).scalars():
        job.salary_quality = assess_salary_quality(
            job.salary_min, job.salary_max, job.salary_period
        )
        key = job.salary_quality or "(no salary)"
        dist[key] = dist.get(key, 0) + 1
    return dist


def apply_remote(session: Session) -> dict[str, int]:
    changed = flagged = 0
    for job in session.execute(select(Job)).scalars():
        loc_display = None  # Adzuna display name lives in the raw response; title+description carry the signal
        # Fullest text available, as scope and skills use: USAJobs keeps its
        # telework language in description_full; Adzuna has only description.
        new_value = detect_remote(job.title, loc_display, job.description_full or job.description)
        if new_value != job.is_remote:
            changed += 1
        job.is_remote = new_value
        flagged += int(new_value)
    return {"remote_true": flagged, "changed_vs_previous": changed}


def apply_metro(session: Session) -> dict[str, int]:
    dist: dict[str, int] = {}
    for loc in session.execute(select(Location)).scalars():
        loc.metro_area = assign_metro(loc.city, loc.state)
        key = loc.metro_area or "(none)"
        dist[key] = dist.get(key, 0) + 1
    return dist


def apply_scope(session: Session) -> dict[str, int]:
    extractor = SkillExtractor()
    dist: dict[str, int] = {}
    for job in session.execute(select(Job)).scalars():
        text = f"{job.title or ''}\n{job.description_full or job.description or ''}"
        job.in_scope, job.scope_reason = classify_scope(job.source, job.category, text, extractor)
        key = "in_scope" if job.in_scope else "out_of_scope"
        dist[key] = dist.get(key, 0) + 1
    return dist


def _usajobs_key_requirements(session: Session, job: Job, cache: dict) -> list[str] | None:
    """KeyRequirements for a USAJobs job, read from the raw page it was last
    parsed from (MatchedObjectId == external_id). None when absent."""
    if job.source != "usajobs" or job.raw_response_id is None:
        return None
    if job.raw_response_id not in cache:
        raw = session.get(RawResponse, job.raw_response_id)
        items = (raw.response if raw else {}).get("SearchResult", {}).get("SearchResultItems", [])
        cache[job.raw_response_id] = {
            str(item.get("MatchedObjectId")): (
                (item.get("MatchedObjectDescriptor") or {})
                .get("UserArea", {})
                .get("Details", {})
                .get("KeyRequirements")
            )
            for item in items
        }
    return cache[job.raw_response_id].get(job.external_id) or None


def apply_visa(session: Session) -> dict[str, int]:
    """Rebuild job_visa_signals for every job (the view filters to in-scope)."""
    session.execute(delete(JobVisaSignal))
    raw_cache: dict = {}
    dist: dict[str, int] = {}
    rows = session.execute(
        select(Job, Company.canonical_name).outerjoin(Company, Company.id == Job.company_id)
    ).all()
    for job, company_name in rows:
        signals = classify_posting(
            job.title,
            job.description,
            job.description_full,
            company_name,
            _usajobs_key_requirements(session, job, raw_cache),
        )
        session.add(JobVisaSignal(job_id=job.id, **asdict(signals)))
        for key in (
            f"restriction:{signals.restriction}",
            f"stance:{signals.sponsorship_stance}",
            f"coverage:{signals.text_coverage}",
            f"cap_exempt:{signals.cap_exempt_hint}",
        ):
            dist[key] = dist.get(key, 0) + 1
        dist["opt_mentioned"] = dist.get("opt_mentioned", 0) + int(signals.opt_mentioned)
    return dict(sorted(dist.items()))


def extract_for_all_jobs(
    session: Session,
    skill_ids: dict[str, int],
    min_confidence: float = 0.0,
    extractor: SkillExtractor | None = None,
) -> tuple[int, int]:
    """Run extraction over every job and converge `job_skills` on it.

    Returns (jobs_processed, links_written), where links_written is the
    number of current links (matches at or above `min_confidence`), as
    before. Stale links are deleted; their count is logged. `extractor`
    defaults to one built from the taxonomy file (tests pass their own).
    """
    extractor = extractor or SkillExtractor()
    jobs_processed = links_written = links_deleted = 0
    offset = 0
    while True:
        batch = session.execute(
            select(Job.id, Job.title, Job.description, Job.description_full)
            .order_by(Job.id)
            .offset(offset)
            .limit(REFERENCE_BATCH_SIZE)
        ).all()
        if not batch:
            break
        batch_ids = [row[0] for row in batch]
        existing: dict[int, set[int]] = {}
        for job_id, skill_id in session.execute(
            select(JobSkill.job_id, JobSkill.skill_id).where(JobSkill.job_id.in_(batch_ids))
        ):
            existing.setdefault(job_id, set()).add(skill_id)
        for job_id, title, description, description_full in batch:
            text = f"{title or ''}\n{description_full or description or ''}"
            wanted: set[int] = set()
            for skill_name, confidence in extractor.extract(text).items():
                if confidence < min_confidence:
                    continue
                skill_id = skill_ids[skill_name]
                wanted.add(skill_id)
                stmt = (
                    pg_insert(JobSkill)
                    .values(job_id=job_id, skill_id=skill_id, confidence=confidence)
                    .on_conflict_do_update(
                        index_elements=[JobSkill.job_id, JobSkill.skill_id],
                        set_={"confidence": confidence},
                    )
                )
                session.execute(stmt)
                links_written += 1
            stale = existing.get(job_id, set()) - wanted
            if stale:
                session.execute(
                    delete(JobSkill).where(
                        JobSkill.job_id == job_id, JobSkill.skill_id.in_(sorted(stale))
                    )
                )
                links_deleted += len(stale)
            jobs_processed += 1
        offset += REFERENCE_BATCH_SIZE
    return jobs_processed, links_written
