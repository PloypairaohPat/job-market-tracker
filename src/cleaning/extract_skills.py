"""Extract skills for all jobs in the database.

Run:  python -m src.cleaning.extract_skills [--min-confidence 0.5] [--rebuild]

Steps:
  1. Sync the taxonomy JSON into the `skills` table (upsert by name).
  2. For every job, run the extractor over title + description and
     upsert (job_id, skill_id, confidence) rows into `job_skills`.

Idempotent: re-running converges on the same state. `--rebuild` first
clears `job_skills`, for when the taxonomy changes shape (e.g. a skill
was removed) — this is the raw-then-normalized pattern in action:
extraction is a *derived layer* that can always be recomputed from the
stored descriptions.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.cleaning.skill_extractor import SkillExtractor, load_taxonomy
from src.models import Job, JobSkill, Skill
from src.utils.db import session_scope

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def sync_taxonomy(session: Session) -> dict[str, int]:
    """Upsert taxonomy entries into `skills`; return name -> id map."""
    for sdef in load_taxonomy():
        stmt = (
            pg_insert(Skill)
            .values(name=sdef.name, category=sdef.category, aliases=[])
            .on_conflict_do_update(
                index_elements=[Skill.name],
                set_={"category": sdef.category},
            )
        )
        session.execute(stmt)
    rows = session.execute(select(Skill.name, Skill.id)).all()
    return dict(rows)


def extract_for_all_jobs(
    session: Session,
    skill_ids: dict[str, int],
    min_confidence: float = 0.0,
) -> tuple[int, int]:
    """Run extraction over every job. Returns (jobs_processed, links_written)."""
    extractor = SkillExtractor()
    jobs_processed = links_written = 0
    offset = 0
    while True:
        batch = session.execute(
            select(Job.id, Job.title, Job.description)
            .order_by(Job.id)
            .offset(offset)
            .limit(BATCH_SIZE)
        ).all()
        if not batch:
            break
        for job_id, title, description in batch:
            text = f"{title or ''}\n{description or ''}"
            for skill_name, confidence in extractor.extract(text).items():
                if confidence < min_confidence:
                    continue
                stmt = (
                    pg_insert(JobSkill)
                    .values(job_id=job_id, skill_id=skill_ids[skill_name], confidence=confidence)
                    .on_conflict_do_update(
                        index_elements=[JobSkill.job_id, JobSkill.skill_id],
                        set_={"confidence": confidence},
                    )
                )
                session.execute(stmt)
                links_written += 1
            jobs_processed += 1
        offset += BATCH_SIZE
    return jobs_processed, links_written


def report_top_skills(session: Session, limit: int = 15) -> None:
    rows = session.execute(
        select(Skill.name, func.count(JobSkill.job_id).label("jobs"))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .group_by(Skill.name)
        .order_by(func.count(JobSkill.job_id).desc())
        .limit(limit)
    ).all()
    total_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
    logger.info("Top skills by job mentions (of %d jobs):", total_jobs)
    for name, n in rows:
        logger.info("  %-20s %5d  (%.1f%%)", name, n, 100.0 * n / max(total_jobs, 1))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Extract skills for all jobs.")
    argp.add_argument("--min-confidence", type=float, default=0.0)
    argp.add_argument(
        "--rebuild",
        action="store_true",
        help="clear job_skills before extracting (taxonomy shape changed)",
    )
    args = argp.parse_args()

    with session_scope() as session:
        if args.rebuild:
            session.execute(delete(JobSkill))
            logger.info("Cleared job_skills for rebuild.")
        skill_ids = sync_taxonomy(session)
        logger.info("Taxonomy synced: %d skills.", len(skill_ids))
        jobs, links = extract_for_all_jobs(session, skill_ids, args.min_confidence)
        logger.info("Processed %d jobs, wrote %d job-skill links.", jobs, links)
        report_top_skills(session)


if __name__ == "__main__":
    main()
