"""F: the private shortlist (src/shortlist.py), on invented rows only."""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src import shortlist as sl
from src.shortlist import Profile, ProfileError

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[1]
SKILLS = ["SQL", "Python", "Tableau", "Excel"]
NOW = datetime(2026, 3, 9, 12, tzinfo=UTC)


def row(**over) -> dict:
    base = {
        "job_id": 1,
        "source": "adzuna",
        "title": "Data Analyst",
        "title_key": "data analyst",
        "employer_key": "fakeco one",
        "employer": "FAKECO One",
        "city": "New York",
        "state": "New York",
        "metro_area": "NYC",
        "is_remote": False,
        "seniority": None,
        "salary_min": None,
        "salary_max": None,
        "salary_period": None,
        "salary_currency": "USD",
        "salary_is_predicted": None,
        "salary_quality": None,
        "redirect_url": "https://example.invalid/1",
        "first_seen_at": NOW,
        "visa_bucket": "unknown",
        "skills": [],
    }
    return {**base, **over}


# --------------------------------------------------------------------- #
# the profile


def test_example_profile_parses_to_the_defaults():
    profile = sl.load_profile(ROOT / "shortlist.example.toml", SKILLS)
    assert profile == Profile()


def test_profile_values_and_skill_case_is_normalised():
    p = sl.parse_profile(
        {
            "lookback_days": 14,
            "title_include": ["analyst", " "],
            "skills_any": ["sql", "PYTHON"],
            "metros": ["NYC", "DC"],
            "seniority": ["junior"],
            "min_salary": 70000,
            "visa_buckets": ["strong", "possible"],
            "include_remote": False,
        },
        SKILLS,
    )
    assert p.lookback_days == 14 and p.title_include == ("analyst",)
    assert p.skills_any == ("SQL", "Python")
    assert p.metros == ("NYC", "DC") and not p.include_remote


@pytest.mark.parametrize(
    "raw, says",
    [
        ({"lookback": 7}, "unknown option(s): lookback"),
        ({"metros": ["Denver"]}, "metros: Denver not recognised"),
        ({"seniority": ["entry"]}, "seniority: entry not recognised"),
        ({"visa_buckets": ["yes"]}, "visa_buckets: yes not recognised"),
        ({"skills_all": ["Excell"]}, "skills_all: excell not recognised"),
        ({"min_salary": "70k"}, "min_salary must be a whole number"),
        ({"lookback_days": 0}, "lookback_days must be at least 1"),
        ({"include_remote": "yes"}, "include_remote must be true or false"),
        ({"title_include": "analyst"}, "title_include must be a list of strings"),
    ],
)
def test_profile_errors_name_the_problem(raw, says):
    with pytest.raises(ProfileError, match=says.replace("(", r"\(").replace(")", r"\)")):
        sl.parse_profile(raw, SKILLS)


def test_bad_toml_is_a_profile_error(tmp_path):
    path = tmp_path / "shortlist.toml"
    path.write_text("lookback_days = \n", encoding="utf-8")
    with pytest.raises(ProfileError, match="isn't valid TOML"):
        sl.load_profile(path, SKILLS)


# --------------------------------------------------------------------- #
# each filter


def test_title_include_and_exclude():
    p = Profile(title_include=("analyst",), title_exclude=("intern",))
    assert sl.keep(row(title="Data Analyst"), p)
    assert not sl.keep(row(title="Data Engineer"), p)
    assert not sl.keep(row(title="Data Analyst Intern"), p)
    assert sl.keep(row(title="DATA ANALYST"), p)  # case-insensitive


def test_skills_any_and_all():
    assert sl.keep(row(skills=["SQL"]), Profile(skills_any=("SQL", "Python")))
    assert not sl.keep(row(skills=["Excel"]), Profile(skills_any=("SQL", "Python")))
    assert sl.keep(row(skills=["SQL", "Python"]), Profile(skills_all=("SQL", "Python")))
    assert not sl.keep(row(skills=["SQL"]), Profile(skills_all=("SQL", "Python")))


def test_metros_and_remote():
    nyc_only = Profile(metros=("NYC",), include_remote=False)
    assert sl.keep(row(metro_area="NYC"), nyc_only)
    assert not sl.keep(row(metro_area="DC"), nyc_only)
    assert not sl.keep(row(metro_area=None, is_remote=True), nyc_only)
    nyc_or_remote = Profile(metros=("NYC",), include_remote=True)
    assert sl.keep(row(metro_area=None, is_remote=True), nyc_or_remote)
    assert not sl.keep(row(metro_area=None, is_remote=False), nyc_or_remote)
    # no metros: any location; include_remote = false drops remote postings
    assert sl.keep(row(metro_area=None), Profile())
    assert not sl.keep(row(is_remote=True), Profile(include_remote=False))


def test_seniority_and_the_no_signal_rule():
    p = Profile(seniority=("junior", "mid"))
    assert sl.keep(row(seniority="junior"), p)
    assert not sl.keep(row(seniority="senior"), p)
    assert sl.keep(row(seniority=None), p)  # no title signal: kept by default
    strict = Profile(seniority=("junior",), include_no_seniority_signal=False)
    assert not sl.keep(row(seniority=None), strict)
    entry = sl.collapse([row(seniority=None)])[0]
    assert entry.seniority == "no title signal"


def test_no_signal_rule_applies_without_a_seniority_list():
    # the example profile and docs say no-signal postings are kept "unless
    # include_no_seniority_signal = false", with no condition on `seniority`
    p = Profile(include_no_seniority_signal=False)
    assert not sl.keep(row(seniority=None), p)
    assert sl.keep(row(seniority="senior"), p)
    assert sl.keep(row(seniority=None), Profile())


def test_salary_minimum_applies_to_disclosed_salaries_only():
    p = Profile(min_salary=80000)
    low = {"salary_min": 60000, "salary_max": 70000, "salary_period": "year"}
    assert not sl.keep(row(**low, salary_is_predicted=False, salary_quality="ok"), p)
    assert sl.keep(row(**low, salary_is_predicted=True, salary_quality="ok"), p)  # estimate
    assert sl.keep(row(**low, salary_is_predicted=False, salary_quality="suspect_inverted"), p)
    assert sl.keep(row(), p)  # no salary: kept
    opted_in = Profile(min_salary=80000, min_salary_uses_predicted=True)
    assert not sl.keep(row(**low, salary_is_predicted=True, salary_quality="ok"), opted_in)
    # the top of the range counts, annualized: $40/hour * 2080 = $83,200
    hourly = {"salary_min": 30, "salary_max": 40, "salary_period": "hour"}
    assert sl.keep(row(**hourly, salary_is_predicted=False, salary_quality="ok"), p)
    assert sl.annual_salary(row(salary_min=5000, salary_period="month")) == 60000


def test_salary_basis_is_shown():
    assert sl.salary_text(
        row(salary_min=60000, salary_max=70000, salary_period="year", salary_is_predicted=True)
    ) == ("$60,000–$70,000 a year", "Adzuna's estimate")
    assert sl.salary_text(
        row(salary_min=90000, salary_max=90000, salary_period="year", salary_is_predicted=False)
    ) == ("$90,000 a year", "employer-disclosed")
    assert sl.salary_text(
        row(
            salary_min=9, salary_max=8, salary_is_predicted=False, salary_quality="suspect_inverted"
        )
    ) == ("$9–$8", "employer-disclosed; flagged suspect_inverted")
    assert sl.salary_text(row()) == ("", "not given")


def test_visa_buckets():
    p = Profile(visa_buckets=("strong", "possible"))
    assert sl.keep(row(visa_bucket="strong"), p)
    assert not sl.keep(row(visa_bucket="unknown"), p)


# --------------------------------------------------------------------- #
# collapsing reposts and output


def test_reposts_collapse_per_employer_and_title_newest_first():
    rows = [  # newest first, as fetch_postings returns them
        row(job_id=5, first_seen_at=NOW, city="Boston", state="MA", metro_area="Boston"),
        row(job_id=4, employer_key="fakeco two", employer="FAKECO Two", first_seen_at=NOW),
        row(job_id=3, first_seen_at=NOW - timedelta(days=2), skills=["SQL"]),
        row(
            job_id=2,
            first_seen_at=NOW - timedelta(days=3),
            metro_area=None,
            is_remote=True,
            city=None,
            state=None,
        ),
        row(
            job_id=1,
            title="Senior Data Analyst",
            title_key="senior data analyst",
            first_seen_at=NOW - timedelta(days=4),
        ),
    ]
    entries = sl.collapse(rows)
    assert [(e.employer, e.title, e.postings) for e in entries] == [
        ("FAKECO One", "Data Analyst", 3),
        ("FAKECO Two", "Data Analyst", 1),
        ("FAKECO One", "Senior Data Analyst", 1),
    ]
    first = entries[0]
    assert first.job_ids == [5, 3, 2]
    assert first.locations == ["Boston, MA (Boston)", "New York, New York (NYC)", "remote"]
    assert first.skills == ["SQL"] and first.first_seen == "2026-03-09"


def test_postings_without_an_employer_are_never_merged():
    rows = [
        row(job_id=7, employer_key=None, employer=None, redirect_url="https://example.invalid/7"),
        row(job_id=6, employer_key=None, employer=None, redirect_url="https://example.invalid/6"),
    ]
    entries = sl.collapse(rows)
    assert [(e.job_ids, e.postings) for e in entries] == [([7], 1), ([6], 1)]
    assert [e.link for e in entries] == ["https://example.invalid/7", "https://example.invalid/6"]


def test_markdown_and_csv_for_entries_and_for_an_empty_result(tmp_path):
    entries = sl.collapse([row(skills=["SQL"])])
    md = sl.render_markdown(entries, Profile(), NOW, "127.0.0.1/jobmarket_test", True)
    assert "Private: this file names postings" in md
    assert "**Synthetic demo data, not real postings.**" in md
    assert md.count(sl.TRUNCATION_CAVEAT) == 1
    assert "## Data Analyst, FAKECO One" in md and "- Visa outlook: unknown" in md
    assert "1 entry." in md

    empty = sl.render_markdown([], Profile(), NOW, "127.0.0.1/jobmarket_test", False)
    assert "0 entries." in empty and "Synthetic" not in empty
    assert sl.TRUNCATION_CAVEAT not in empty
    path = tmp_path / "x.csv"
    sl.write_csv([], path)
    assert list(csv.reader(path.open())) == [list(sl.CSV_COLUMNS)]


# --------------------------------------------------------------------- #
# the output directory


def fake_git(tracked: str = "", ignored: bool = True, fails: bool = False):
    def run(args, cwd):
        if fails:
            return 128, ""
        if args[0] == "ls-files":
            return 0, tracked
        return (0 if ignored else 1), ""

    return run


def test_refuses_a_tracked_or_unignored_directory(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(sl.UnsafeOutputError, match="docs holds files git tracks"):
        sl.check_output_dir(root / "docs", root, fake_git(tracked="docs/README.md\n"))
    with pytest.raises(sl.UnsafeOutputError, match="isn't gitignored"):
        sl.check_output_dir(root / "notes", root, fake_git(ignored=False))
    with pytest.raises(sl.UnsafeOutputError, match="can't ask git"):
        sl.check_output_dir(root / "data" / "shortlist", root, fake_git(fails=True))
    sl.check_output_dir(root / "data" / "shortlist", root, fake_git())  # ignored: fine
    sl.check_output_dir(tmp_path / "elsewhere", root, fake_git(fails=True))  # outside


def test_real_git_refuses_docs_and_accepts_data_shortlist():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    with pytest.raises(sl.UnsafeOutputError):
        sl.check_output_dir(ROOT / "docs")
    sl.check_output_dir(ROOT / "data" / "shortlist")


def test_missing_profile_says_how_to_create_one(tmp_path, capsys):
    code = sl.main(["--profile", str(tmp_path / "shortlist.toml")])
    err = capsys.readouterr().err
    assert code == 2
    assert 'Copy-Item "shortlist.example.toml" "shortlist.toml"' in err


def test_profile_problem_exits_non_zero(tmp_path, capsys):
    path = tmp_path / "shortlist.toml"
    path.write_text('metros = ["Denver"]\n', encoding="utf-8")
    assert sl.main(["--profile", str(path)]) == 2
    assert "metros: Denver not recognised" in capsys.readouterr().err


# --------------------------------------------------------------------- #
# end to end on the demo seed


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_runs_on_the_demo_seed_with_the_example_profile(tmp_path):
    from scripts.seed_demo_data import seed_full
    from src.utils.db import dispose_engines
    from tests.conftest import reset_schema

    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    engine.dispose()
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "candidates.csv")
    dispose_engines()
    profile = sl.load_profile(ROOT / "shortlist.example.toml")
    out = tmp_path / "out"
    entries, path = sl.run(TEST_DB_URL, profile, out)
    assert entries and path == out / f"shortlist-{datetime.now(UTC):%Y-%m-%d}.md"
    text = path.read_text(encoding="utf-8")
    assert "**Synthetic demo data, not real postings.**" in text
    rows = list(csv.DictReader(path.with_suffix(".csv").open(encoding="utf-8")))
    assert len(rows) == len(entries)
    assert sum(int(r["postings"]) for r in rows) >= len(rows)

    narrow = sl.run(TEST_DB_URL, Profile(skills_all=("SQL",)), tmp_path / "n")[0]
    wide_ids = {i for e in entries for i in e.job_ids}
    narrow_ids = {i for e in narrow for i in e.job_ids}
    assert narrow_ids and narrow_ids < wide_ids  # a filter only removes postings
    assert all("SQL" in e.skills for e in narrow)
