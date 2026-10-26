"""Cross-set company <-> LCA employer candidate finder."""

import csv
import os

import pytest
from sqlalchemy import create_engine

from src.cleaning.company_normalizer import ALIASES_PATH
from src.models import Company
from src.utils.db import session_scope
from src.visa.sponsor_match import find_sponsor_match_candidates, write_candidates
from tests.conftest import reset_schema
from tests.visa_helpers import insert_lca, lca

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


def _pairs(cands):
    return {(c["company_key"], c["lca_employer_key"], c["relation"]) for c in cands}


def test_containment_found_and_unrelated_names_not():
    cands = find_sponsor_match_candidates(
        company_keys=["fakeco", "fake northfield university", "fakebank"],
        employer_keys=["fakeco analytics", "fake northfield universty", "zeta fake widgets"],
    )
    pairs = _pairs(cands)
    assert ("fakeco", "fakeco analytics", "containment") in pairs
    assert ("fake northfield university", "fake northfield universty", "fuzzy") in pairs
    assert not any("zeta" in p[1] or p[0] == "fakebank" for p in pairs)


def test_exact_pair_is_skipped_but_longer_variants_are_still_proposed():
    # the exact pair already joins in v_job_visa_outlook -- nothing to review --
    # but other LCA employers in the same block may be the same company
    cands = find_sponsor_match_candidates(
        ["fakeco"], ["fakeco", "fakeco holdings", "fakeco analytics", "fakecorp widgets"]
    )
    pairs = _pairs(cands)
    assert ("fakeco", "fakeco", "fuzzy") not in pairs
    assert not any(employer == "fakeco" for _, employer, _ in pairs)
    assert ("fakeco", "fakeco holdings", "containment") in pairs
    assert ("fakeco", "fakeco analytics", "containment") in pairs
    assert not any(employer == "fakecorp widgets" for _, employer, _ in pairs)  # other block


def test_exact_match_only_yields_nothing():
    assert find_sponsor_match_candidates(["fakeco"], ["fakeco"]) == []


def test_blocking_is_by_first_token():
    # same tail, different first word -> different block, never compared
    cands = find_sponsor_match_candidates(["alpha fake labs"], ["beta fake labs"])
    assert cands == []


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_writes_review_csv_and_never_touches_aliases(tmp_path):
    aliases_before = ALIASES_PATH.read_bytes()
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    with session_scope(TEST_DB_URL) as session:
        session.add_all(
            [
                Company(canonical_name="FAKECO", normalized_name="fakeco", raw_names=["FAKECO"]),
                Company(
                    canonical_name="FAKE Unrelated Bakery",
                    normalized_name="fake unrelated bakery",
                    raw_names=["FAKE Unrelated Bakery"],
                ),
            ]
        )
        insert_lca(session, [lca("FAKECO Analytics LLC"), lca("FAKE Quantum Rockets Inc")])

    out = tmp_path / "sponsor_match_candidates.csv"
    with session_scope(TEST_DB_URL) as session:
        n = write_candidates(session, out)
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None

    rows = list(csv.DictReader(out.open()))
    assert n == 1
    assert rows == [
        {
            "company_key": "fakeco",
            "lca_employer_key": "fakeco analytics",
            "relation": "containment",
            "similarity": "1.0",
            "approved": "",
        }
    ]
    assert ALIASES_PATH.read_bytes() == aliases_before
