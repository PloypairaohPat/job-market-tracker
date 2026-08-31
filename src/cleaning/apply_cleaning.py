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

Everything here derives from stored raw values (titles, descriptions,
cities) and can be rebuilt after any rule change — the raw-then-
normalized pattern applied to cleaning.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.cleaning.company_normalizer import find_merge_candidates, normalize_company_name
from src.cleaning.metro import assign_metro
from src.cleaning.remote import detect_remote
from src.cleaning.salary_quality import assess_salary_quality
from src.cleaning.scope_classifier import classify_scope
from src.cleaning.seniority import classify_seniority
from src.cleaning.skill_extractor import SkillExtractor
from src.models import Company, Job, Location
from src.utils.db import session_scope

logger = logging.getLogger(__name__)

ALL_STEPS = ("seniority", "salary", "remote", "metro", "companies", "scope")
DEFAULT_CANDIDATES_OUT = Path("data/company_merge_candidates.csv")


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
        new_value = detect_remote(job.title, loc_display, job.description)
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
    extractor = SkillExtractor()
    dist: dict[str, int] = {}
    for job in session.execute(select(Job)).scalars():
        text = f"{job.title or ''}\n{job.description_full or job.description or ''}"
        job.in_scope, job.scope_reason = classify_scope(job.source, job.category, text, extractor)
        key = "in_scope" if job.in_scope else "out_of_scope"
        dist[key] = dist.get(key, 0) + 1
    return dist


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Apply Phase 2 cleaning to the database.")
    argp.add_argument("--only", nargs="*", choices=ALL_STEPS, default=None)
    argp.add_argument("--candidates-out", type=Path, default=DEFAULT_CANDIDATES_OUT)
    args = argp.parse_args()

    steps = tuple(args.only) if args.only else ALL_STEPS
    with session_scope() as session:
        if "seniority" in steps:
            logger.info("seniority: %s", apply_seniority(session))
        if "salary" in steps:
            logger.info("salary_quality: %s", apply_salary_quality(session))
        if "remote" in steps:
            logger.info("remote: %s", apply_remote(session))
        if "metro" in steps:
            logger.info("metro: %s", apply_metro(session))
        if "companies" in steps:
            logger.info("companies: %s", apply_companies(session, args.candidates_out))
            summarize_normalization_effect(session)
        if "scope" in steps:
            logger.info("scope: %s", apply_scope(session))


if __name__ == "__main__":
    main()
