"""Apply the Phase 2 cleaning layer to the database.

Run:  python -m src.cleaning.apply_cleaning [--only STEP ...] [--candidates-out PATH]

Steps (all idempotent — the layer is recomputable at any time):
  seniority   classify jobs.seniority from titles
  salary      assess jobs.salary_quality
  remote      upgrade jobs.is_remote with description-level signals
  metro       assign locations.metro_area from (city, state)
  companies   set companies.normalized_name; write fuzzy merge
              candidates to a CSV for MANUAL review (never auto-merged)
  scope       set jobs.in_scope / jobs.scope_reason (flag, never delete)
  visa        rebuild job_visa_signals from posting text, company name and
              (USAJobs) the raw response's KeyRequirements -- see
              src/visa/posting_signals.py

Everything here derives from stored raw values (titles, descriptions,
cities) and can be rebuilt after any rule change — the raw-then-
normalized pattern applied to cleaning.
"""

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import Integer, cast, column, delete, func, insert, select, update, values
from sqlalchemy.orm import Session

from src.cleaning.company_normalizer import find_merge_candidates, normalize_company_name
from src.cleaning.metro import assign_metro
from src.cleaning.remote import detect_remote
from src.cleaning.salary_quality import assess_salary_quality
from src.cleaning.scope_classifier import classify_scope
from src.cleaning.seniority import classify_seniority
from src.cleaning.skill_extractor import SkillExtractor
from src.models import Company, Job, JobVisaSignal, Location, RawResponse
from src.utils.db import session_scope
from src.visa.posting_signals import classify_posting

logger = logging.getLogger(__name__)

ALL_STEPS = ("seniority", "salary", "remote", "metro", "companies", "scope", "visa")
DEFAULT_CANDIDATES_OUT = Path("data/company_merge_candidates.csv")


JOB_STEPS = ("seniority", "salary", "remote", "scope")
JOB_BATCH_SIZE = 2000
_JOB_COLUMNS = {
    "seniority": ("seniority",),
    "salary": ("salary_quality",),
    "remote": ("is_remote",),
    "scope": ("in_scope", "scope_reason"),
}


def apply_job_steps(session: Session, steps: tuple[str, ...] = JOB_STEPS) -> dict[str, dict]:
    """Run the job-level steps in one pass over `jobs`; return {step: its counts}.

    The steps (seniority, salary quality, remote, scope) each read only the
    stored raw columns, never each other's output, so one read serves all
    of them. Rows are read in keyset batches as plain tuples (no ORM
    objects), and only rows whose derived values changed are written, one
    UPDATE ... FROM (VALUES ...) statement per batch. The counts are the
    same dictionaries the per-step functions always returned.
    """
    steps = tuple(step for step in JOB_STEPS if step in steps)
    if not steps:
        return {}
    session.flush()  # a caller's pending ORM changes are part of what we read
    extractor = SkillExtractor() if "scope" in steps else None
    counts: dict[str, dict[str, int]] = {step: {} for step in steps}
    if "remote" in steps:
        counts["remote"] = {"remote_true": 0, "changed_vs_previous": 0}
    written = [col for step in steps for col in _JOB_COLUMNS[step]]
    jobs = Job.__table__
    last_id = 0
    while True:
        batch = session.execute(
            select(
                jobs.c.id,
                jobs.c.source,
                jobs.c.category,
                jobs.c.title,
                jobs.c.description,
                jobs.c.description_full,
                jobs.c.salary_min,
                jobs.c.salary_max,
                jobs.c.salary_period,
                *(jobs.c[col] for col in written),
            )
            .where(jobs.c.id > last_id)
            .order_by(jobs.c.id)
            .limit(JOB_BATCH_SIZE)
        ).all()
        if not batch:
            break
        last_id = batch[-1].id
        changes = []
        for row in batch:
            new: dict[str, object] = {}
            if "seniority" in steps:
                new["seniority"] = classify_seniority(row.title)
                _bump(counts["seniority"], new["seniority"] or "(none)")
            if "salary" in steps:
                new["salary_quality"] = assess_salary_quality(
                    row.salary_min, row.salary_max, row.salary_period
                )
                _bump(counts["salary"], new["salary_quality"] or "(no salary)")
            if "remote" in steps:
                # Fullest text available, as scope and skills use: USAJobs keeps its
                # telework language in description_full; Adzuna has only description.
                # (The Adzuna display location lives in the raw response; title and
                # description carry the signal.)
                new["is_remote"] = detect_remote(
                    row.title, None, row.description_full or row.description
                )
                counts["remote"]["changed_vs_previous"] += int(new["is_remote"] != row.is_remote)
                counts["remote"]["remote_true"] += int(new["is_remote"])
            if "scope" in steps:
                text_ = f"{row.title or ''}\n{row.description_full or row.description or ''}"
                new["in_scope"], new["scope_reason"] = classify_scope(
                    row.source, row.category, text_, extractor
                )
                _bump(counts["scope"], "in_scope" if new["in_scope"] else "out_of_scope")
            if any(new[col] != getattr(row, col) for col in written):
                changes.append({"id": row.id, **new})
        if changes:
            _update_jobs(session, written, changes)
    session.expire_all()  # ORM objects a caller holds must re-read what we wrote
    return counts


def _bump(dist: dict[str, int], key: str) -> None:
    dist[key] = dist.get(key, 0) + 1


def _update_jobs(session: Session, written: list[str], changes: list[dict]) -> None:
    """One UPDATE jobs ... FROM (VALUES ...) for a batch of changed rows."""
    jobs = Job.__table__
    data = values(
        column("id", Integer),
        *(column(col, jobs.c[col].type) for col in written),
        name="changed",
    ).data([tuple(change[k] for k in ("id", *written)) for change in changes])
    session.execute(
        update(jobs)
        .where(jobs.c.id == data.c.id)
        # an all-NULL VALUES column is typed text by Postgres: cast back
        .values({col: cast(data.c[col], jobs.c[col].type) for col in written})
    )


def apply_seniority(session: Session) -> dict[str, int]:
    return apply_job_steps(session, ("seniority",))["seniority"]


def apply_salary_quality(session: Session) -> dict[str, int]:
    return apply_job_steps(session, ("salary",))["salary"]


def apply_remote(session: Session) -> dict[str, int]:
    return apply_job_steps(session, ("remote",))["remote"]


def apply_metro(session: Session) -> dict[str, int]:
    dist: dict[str, int] = {}
    for loc in session.execute(select(Location)).scalars():
        loc.metro_area = assign_metro(loc.city, loc.state)
        key = loc.metro_area or "(none)"
        dist[key] = dist.get(key, 0) + 1
    return dist


def apply_companies(session: Session, candidates_out: Path) -> dict[str, int]:
    names: list[str] = []
    for company in session.execute(select(Company)).scalars():
        company.normalized_name = normalize_company_name(company.canonical_name)
        names.append(company.normalized_name)

    raw_count = len(names)
    normalized_count = len(set(names))

    candidates = find_merge_candidates(names)
    candidates_out.parent.mkdir(parents=True, exist_ok=True)
    with candidates_out.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["name_a", "name_b", "relation", "similarity", "approved"]
        )
        writer.writeheader()
        for cand in candidates:
            writer.writerow({**cand, "approved": ""})
    logger.info(
        "Wrote %d merge candidates for manual review -> %s "
        "(fill the 'approved' column, then promote approved pairs into company_aliases.json)",
        len(candidates),
        candidates_out,
    )
    return {
        "raw_names": raw_count,
        "normalized_keys": normalized_count,
        "merged_by_rules": raw_count - normalized_count,
        "review_candidates": len(candidates),
    }


def apply_scope(session: Session) -> dict[str, int]:
    return apply_job_steps(session, ("scope",))["scope"]


VISA_BATCH_SIZE = 2000


def _key_requirements_by_page(session: Session, raw_ids: set[int]) -> dict[int, dict]:
    """{raw_response_id: {MatchedObjectId: KeyRequirements}} for USAJobs pages,
    read in one query. A page that no longer exists maps to {}."""
    found: dict[int, dict] = {raw_id: {} for raw_id in raw_ids}
    if not raw_ids:
        return found
    for raw_id, response in session.execute(
        select(RawResponse.id, RawResponse.response).where(RawResponse.id.in_(sorted(raw_ids)))
    ):
        items = (response or {}).get("SearchResult", {}).get("SearchResultItems", [])
        found[raw_id] = {
            str(item.get("MatchedObjectId")): (
                (item.get("MatchedObjectDescriptor") or {})
                .get("UserArea", {})
                .get("Details", {})
                .get("KeyRequirements")
            )
            for item in items
        }
    return found


def apply_visa(session: Session) -> dict[str, int]:
    """Rebuild job_visa_signals for every job (the view filters to in-scope).

    Deletes every row, then reads jobs (with the company name) in keyset
    batches and inserts each batch's signals in one multi-row statement.
    USAJobs KeyRequirements come from the raw page each job was last parsed
    from (MatchedObjectId == external_id): one query per batch for the pages
    not read yet, never one per job.
    """
    session.flush()
    session.execute(delete(JobVisaSignal))
    pages: dict[int, dict] = {}
    dist: dict[str, int] = {}
    last_id = 0
    while True:
        batch = session.execute(
            select(
                Job.id,
                Job.source,
                Job.external_id,
                Job.raw_response_id,
                Job.title,
                Job.description,
                Job.description_full,
                Company.canonical_name,
            )
            .outerjoin(Company, Company.id == Job.company_id)
            .where(Job.id > last_id)
            .order_by(Job.id)
            .limit(VISA_BATCH_SIZE)
        ).all()
        if not batch:
            break
        last_id = batch[-1].id
        wanted = {
            row.raw_response_id
            for row in batch
            if row.source == "usajobs" and row.raw_response_id is not None
        }
        pages.update(_key_requirements_by_page(session, wanted - pages.keys()))
        signals_rows = []
        for row in batch:
            key_requirements = None
            if row.source == "usajobs" and row.raw_response_id is not None:
                key_requirements = pages[row.raw_response_id].get(row.external_id) or None
            signals = classify_posting(
                row.title,
                row.description,
                row.description_full,
                row.canonical_name,
                key_requirements,
            )
            signals_rows.append({"job_id": row.id, **asdict(signals)})
            for key in (
                f"restriction:{signals.restriction}",
                f"stance:{signals.sponsorship_stance}",
                f"coverage:{signals.text_coverage}",
                f"cap_exempt:{signals.cap_exempt_hint}",
            ):
                dist[key] = dist.get(key, 0) + 1
            dist["opt_mentioned"] = dist.get("opt_mentioned", 0) + int(signals.opt_mentioned)
        session.execute(insert(JobVisaSignal.__table__), signals_rows)
    session.expire_all()
    return dict(sorted(dist.items()))


def summarize_normalization_effect(session: Session) -> None:
    """Before/after view: top employers by raw vs normalized grouping."""
    top = session.execute(
        select(Company.normalized_name, func.count(Job.id).label("postings"))
        .join(Job, Job.company_id == Company.id)
        .group_by(Company.normalized_name)
        .order_by(func.count(Job.id).desc())
        .limit(10)
    ).all()
    logger.info("Top employers by NORMALIZED name:")
    for name, n in top:
        logger.info("  %-30s %d", name, n)


def run_steps(
    session: Session,
    steps: tuple[str, ...] = ALL_STEPS,
    candidates_out: Path = DEFAULT_CANDIDATES_OUT,
) -> dict[str, dict]:
    """Run the named steps; return {step: its counts}, in ALL_STEPS order.
    The job-level steps (JOB_STEPS) share one pass over `jobs`, which runs
    first; they don't depend on metro or companies. Shared by main() and
    the daily runner (src/pipeline/daily.py)."""
    job_level = apply_job_steps(session, steps)
    results: dict[str, dict] = {}
    for step, label in (("seniority", "seniority"), ("salary", "salary_quality")):
        if step in job_level:
            results[step] = job_level[step]
            logger.info("%s: %s", label, results[step])
    if "remote" in job_level:
        results["remote"] = job_level["remote"]
        logger.info("remote: %s", results["remote"])
    if "metro" in steps:
        results["metro"] = apply_metro(session)
        logger.info("metro: %s", results["metro"])
    if "companies" in steps:
        results["companies"] = apply_companies(session, candidates_out)
        logger.info("companies: %s", results["companies"])
        summarize_normalization_effect(session)
    if "scope" in job_level:
        results["scope"] = job_level["scope"]
        logger.info("scope: %s", results["scope"])
    if "visa" in steps:
        results["visa"] = apply_visa(session)
        logger.info("visa: %s", results["visa"])
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Apply Phase 2 cleaning to the database.")
    argp.add_argument("--only", nargs="*", choices=ALL_STEPS, default=None)
    argp.add_argument("--candidates-out", type=Path, default=DEFAULT_CANDIDATES_OUT)
    args = argp.parse_args()

    steps = tuple(args.only) if args.only else ALL_STEPS
    with session_scope() as session:
        run_steps(session, steps, args.candidates_out)


if __name__ == "__main__":
    main()
