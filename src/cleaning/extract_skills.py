"""Extract skills for all jobs in the database.

Run:  python -m src.cleaning.extract_skills [--min-confidence 0.5] [--rebuild]

Steps:
  1. Sync the taxonomy JSON into the `skills` table (upsert by name).
     Skills that have left the taxonomy keep their `skills` row; their
     number is logged as "orphaned".
  2. For every job, run the extractor over title + the full description
     (`description_full`, else `description`) and make the job's
     `job_skills` rows exactly the extractor's matches at or above
     `min_confidence`: new links are inserted, changed confidences
     updated, and links that no longer match are deleted (including
     links to a skill that has left the taxonomy, and every link of a
     job with no text).

Converges: after a run, `job_skills` is a pure function of the stored
text, the taxonomy and `min_confidence`, and a second run changes
nothing. `--rebuild` still clears `job_skills` first; it is no longer
needed for convergence, but it remains a simple way to start over.
Extraction is a *derived layer* that can always be recomputed from the
stored descriptions.
"""

from __future__ import annotations

import argparse
import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.cleaning.skill_extractor import SkillDef, SkillExtractor, load_taxonomy
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
    orphaned = count_orphaned_skills(session)
    if orphaned:
        logger.info(
            "%d skills rows are no longer in the taxonomy (kept; their links are removed "
            "by extraction).",
            orphaned,
        )
    return dict(rows)


def count_orphaned_skills(session: Session, taxonomy: list[SkillDef] | None = None) -> int:
    """How many `skills` rows name a skill the taxonomy no longer has."""
    names = {sdef.name for sdef in (taxonomy if taxonomy is not None else load_taxonomy())}
    existing = session.execute(select(Skill.name)).scalars().all()
    return sum(1 for n in existing if n not in names)


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

    Jobs are read in keyset batches (`WHERE id > :last ORDER BY id LIMIT
    BATCH_SIZE`). Per batch, at most one multi-row upsert writes the links
    that are new or whose confidence changed, and at most one DELETE
    removes the stale ones; links already correct are not rewritten.
    """
    extractor = extractor or SkillExtractor()
    jobs_processed = links_written = links_deleted = 0
    last_id = 0
    while True:
        batch = session.execute(
            select(Job.id, Job.title, Job.description, Job.description_full)
            .where(Job.id > last_id)
            .order_by(Job.id)
            .limit(BATCH_SIZE)
        ).all()
        if not batch:
            break
        last_id = batch[-1][0]
        existing: dict[tuple[int, int], Decimal] = {
            (job_id, skill_id): confidence
            for job_id, skill_id, confidence in session.execute(
                select(JobSkill.job_id, JobSkill.skill_id, JobSkill.confidence).where(
                    JobSkill.job_id.in_([row[0] for row in batch])
                )
            )
        }
        upserts: list[dict] = []
        wanted: set[tuple[int, int]] = set()
        for job_id, title, description, description_full in batch:
            text = f"{title or ''}\n{description_full or description or ''}"
            for skill_name, confidence in extractor.extract(text).items():
                if confidence < min_confidence:
                    continue
                key = (job_id, skill_ids[skill_name])
                wanted.add(key)
                links_written += 1
                if existing.get(key) != _stored(confidence):
                    upserts.append({"job_id": key[0], "skill_id": key[1], "confidence": confidence})
            jobs_processed += 1
        if upserts:
            stmt = pg_insert(JobSkill).values(upserts)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[JobSkill.job_id, JobSkill.skill_id],
                    set_={"confidence": stmt.excluded.confidence},
                )
            )
        stale = sorted(existing.keys() - wanted)
        if stale:
            session.execute(
                delete(JobSkill).where(tuple_(JobSkill.job_id, JobSkill.skill_id).in_(stale))
            )
            links_deleted += len(stale)
    if links_deleted:
        logger.info("Removed %d job-skill links that no longer match.", links_deleted)
    return jobs_processed, links_written


def _stored(confidence: float) -> Decimal:
    """A confidence as job_skills.confidence (numeric(3, 2)) stores it."""
    return Decimal(str(confidence)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
        help="clear job_skills before extracting (not needed for convergence; a clean start)",
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
