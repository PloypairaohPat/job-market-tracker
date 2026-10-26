"""Propose company <-> LCA-employer matches for MANUAL review.

Run:  python -m src.visa.sponsor_match [--out data/sponsor_match_candidates.csv]

`v_job_visa_outlook` joins postings to sponsorship history on exact key
equality (companies.normalized_name = lca_cases.employer_key). Both
sides go through `normalize_company_name`, so most employers line up on
their own; this finder proposes the near-misses ("fakeco" vs "fakeco
analytics") that would otherwise land in the `unknown` bucket.

Same rules and cutoff as `find_merge_candidates` (via `classify_pair`),
but cross-set: each company key is compared only with LCA employer keys
that share its FIRST TOKEN (blocking), never all pairs -- LCA files hold
tens of thousands of employers per year. Consequence: a typo in the
first word is never proposed. Exact matches are skipped (they already
join).

Never auto-merges. The CSV carries an empty `approved` column; the owner
reviews it and promotes approved pairs into
src/cleaning/data/company_aliases.json (see src/visa/README.md).
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cleaning.company_normalizer import DEFAULT_SIMILARITY_CUTOFF, classify_pair
from src.models import Company, LcaCase
from src.utils.db import session_scope

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("data/sponsor_match_candidates.csv")
FIELDNAMES = ["company_key", "lca_employer_key", "relation", "similarity", "approved"]


def _first_token(name: str) -> str:
    return name.split(" ", 1)[0]


def find_sponsor_match_candidates(
    company_keys: list[str],
    employer_keys: list[str],
    similarity_cutoff: float = DEFAULT_SIMILARITY_CUTOFF,
) -> list[dict]:
    """Cross-set candidates: {company_key, lca_employer_key, relation, similarity}."""
    employers = set(employer_keys)
    blocks: dict[str, list[str]] = defaultdict(list)
    for key in sorted(employers):
        blocks[_first_token(key)].append(key)

    candidates: list[dict] = []
    for company in sorted(set(company_keys)):
        if not company or company in employers:
            continue  # exact key already joins; nothing to review
        for employer in blocks.get(_first_token(company), ()):
            match = classify_pair(company, employer, similarity_cutoff)
            if match:
                candidates.append({"company_key": company, "lca_employer_key": employer, **match})
    return candidates


def write_candidates(session: Session, out: Path) -> int:
    company_keys = [
        k for k in session.execute(select(Company.normalized_name).distinct()).scalars() if k
    ]
    employer_keys = [
        k for k in session.execute(select(LcaCase.employer_key).distinct()).scalars() if k
    ]
    candidates = find_sponsor_match_candidates(company_keys, employer_keys)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for cand in candidates:
            writer.writerow({**cand, "approved": ""})
    logger.info(
        "Wrote %d sponsor-match candidates for manual review -> %s "
        "(fill the 'approved' column, then promote approved pairs into company_aliases.json)",
        len(candidates),
        out,
    )
    return len(candidates)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Propose company <-> LCA employer matches.")
    argp.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = argp.parse_args()
    with session_scope() as session:
        write_candidates(session, args.out)


if __name__ == "__main__":
    main()
