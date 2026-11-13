"""B1-B4: narrative files, --publish, and the README published-reports block.

Everything runs in temp directories: no test writes docs/reports/ or the
real README.md, and every number is invented (the hand-built frames from the
report tests, or the synthetic demo seed).
"""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.reports import disclosure, employers
from src.reports import publish as pub
from src.reports.catalog import REPORTS
from src.reports.guardrails import GuardrailError
from src.reports.markdown import PLACEHOLDER_MARK
from src.reports.provenance import DEMO_BANNER, REPO_ROOT
from tests import test_report_disclosure as t_disc
from tests import test_report_employers as t_emp

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


class FakeReader:
    """The ViewReader interface over hand-built frames."""

    def __init__(self, frames, database="jobmarket"):
        self.frames = frames
        self.database = database
        self.rows_read = {}

    def read(self, view):
        frame = self.frames[view]
        self.rows_read[view] = len(frame)
        return frame

    def database_name(self):
        return self.database


def readme(tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(f"# Title\n\nintro\n\n{pub.README_START}\nold\n{pub.README_END}\n\n## Next\n")
    return path


def write_narrative(docs: Path, slug: str, sections: dict[str, str]) -> Path:
    path = pub.narrative_path(slug, docs)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"# {slug} narrative"]
    for name, text in sections.items():
        body += ["", f"## {name}", "", text]
    path.write_text("\n".join(body) + "\n")
    return path


GOOD = {
    "Headline": "Invented headline text. Employer-disclosed salary appears on 12.0% of postings.",
    "What it means": "Invented meaning text.\n\nA second paragraph.",
    "What to do about it": "Invented action text.",
}


def disc_reader(database="jobmarket"):
    return FakeReader(t_disc.frames(), database)


# --------------------------------------------------------------------- #
# B1 init


def test_every_report_declares_the_sections_it_renders():
    golden = REPO_ROOT / "tests" / "fixtures" / "reports"
    for slug, module in REPORTS.items():
        md = (golden / f"{slug}.md").read_text()
        rendered = re.findall(rf"\[{PLACEHOLDER_MARK}: ([^\]]+)\]", md)
        assert rendered == list(module.SECTIONS), slug


def test_init_creates_headings_and_comments_and_never_overwrites(tmp_path):
    path, created = pub.init_narrative(disclosure.SLUG, tmp_path)
    assert created and path == tmp_path / disclosure.SLUG / "narrative.md"
    text = path.read_text()
    for section, purpose in disclosure.SECTIONS.items():
        assert f"\n## {section}\n" in text
        assert purpose in text
    assert "v_field_completeness_counts" in text
    assert PLACEHOLDER_MARK in text  # only inside the comments: points at the render
    path.write_text("owner's own text\n")
    again, created = pub.init_narrative(disclosure.SLUG, tmp_path)
    assert again == path and not created
    assert path.read_text() == "owner's own text\n"


def test_a_fresh_template_cannot_be_published(tmp_path):
    pub.init_narrative(disclosure.SLUG, tmp_path)
    with pytest.raises(pub.PublishRefused, match="placeholder mark"):
        pub.publish(disclosure.SLUG, disc_reader(), tmp_path, readme(tmp_path))


def test_init_on_the_cli_never_touches_the_real_docs(tmp_path, monkeypatch):
    from src.reports.__main__ import main

    calls = []
    monkeypatch.setattr(pub, "init_narrative", lambda slug: (calls.append(slug), (tmp_path, 1))[1])
    assert main([disclosure.SLUG, "--init-narrative"]) == 0
    assert calls == [disclosure.SLUG]


# --------------------------------------------------------------------- #
# B2 publish


def test_publish_merges_every_section_and_drops_the_numbers_lists(tmp_path):
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    result = pub.publish(disclosure.SLUG, disc_reader(), tmp_path, readme(tmp_path))
    md = result.path.read_text()
    assert result.path == tmp_path / disclosure.SLUG / "report.md"
    for text in GOOD.values():
        assert text in md
    assert PLACEHOLDER_MARK not in md
    assert "Numbers from this run to draw on" not in md
    assert "| Provenance | |" in md and "| Database | `jobmarket` |" in md
    assert md.index("| Provenance | |") < md.index("## Headline")
    assert "<!-- Published by `python -m src.reports how-much-employers-disclose --publish`" in md
    assert DEMO_BANNER not in md
    assert result.charts == ["measured-fields.png"]
    assert (tmp_path / disclosure.SLUG / "measured-fields.png").stat().st_size > 10_000
    assert result.warnings == []


def test_html_comments_in_the_narrative_are_dropped(tmp_path):
    sections = dict(GOOD, Headline="<!-- a note to self -->\nInvented headline.")
    write_narrative(tmp_path, disclosure.SLUG, sections)
    md = pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None).path.read_text()
    assert "a note to self" not in md and "Invented headline." in md


@pytest.mark.parametrize("database", ["jobmarket_demo", "jobmarket_test", "Demo_copy"])
def test_publish_refuses_a_demo_or_test_database(tmp_path, database):
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    with pytest.raises(pub.PublishRefused, match="never published as findings"):
        pub.publish(disclosure.SLUG, disc_reader(database), tmp_path, readme(tmp_path))
    assert not (tmp_path / disclosure.SLUG / "report.md").exists()


def test_the_test_only_override_keeps_the_demo_banner(tmp_path):
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    result = pub.publish(
        disclosure.SLUG, disc_reader("jobmarket_demo"), tmp_path, None, allow_demo=True
    )
    assert f"> **{DEMO_BANNER}**" in result.path.read_text()


def test_publish_refuses_a_missing_narrative(tmp_path):
    with pytest.raises(pub.PublishRefused, match="--init-narrative"):
        pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None)


@pytest.mark.parametrize(
    ("sections", "reason"),
    [
        (
            {"Headline": "x", "What it means": "y"},
            r"missing section\(s\) \['What to do about it'\]",
        ),
        (dict(GOOD, Headline=""), "'Headline' is empty"),
        (dict(GOOD, Headline="<!-- just a note -->"), "'Headline' is empty"),
        (
            dict(GOOD, Headline=f"<!-- {pub.INIT_COMMENT_TAG} what this is for -->"),
            "holds only the init comment",
        ),
        (dict(GOOD, Headline="[TO WRITE: Headline] later"), "placeholder mark"),
        (dict(GOOD, Headlines="typo"), "unknown section"),
    ],
)
def test_publish_refuses_an_unfinished_narrative(tmp_path, sections, reason):
    write_narrative(tmp_path, disclosure.SLUG, sections)
    with pytest.raises(pub.PublishRefused, match=reason):
        pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None)
    assert not (tmp_path / disclosure.SLUG / "report.md").exists()


def test_publish_refuses_when_a_guardrail_fails(tmp_path):
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    frames = t_disc.frames()
    frames["v_field_completeness"] = frames["v_field_completeness"].assign(n_jobs=1)
    with pytest.raises(GuardrailError):
        pub.publish(disclosure.SLUG, FakeReader(frames), tmp_path, None)
    assert not (tmp_path / disclosure.SLUG / "report.md").exists()


def test_stale_numbers_are_warned_about_with_their_line(tmp_path):
    sections = dict(
        GOOD,
        **{
            "What it means": "Up from 47.5% last month.\n\nThe 12.0% figure holds.",
            "What to do about it": "Ask for $95k, or $1,234.\n<!-- 99.9% in a comment -->",
        },
    )
    path = write_narrative(tmp_path, disclosure.SLUG, sections)
    result = pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None)
    lines = path.read_text().splitlines()
    line_47 = next(i for i, ln in enumerate(lines, 1) if "47.5%" in ln)
    line_95 = next(i for i, ln in enumerate(lines, 1) if "$95k" in ln)
    assert result.warnings == [
        f"narrative.md line {line_47}: 47.5% is not in this run",
        f"narrative.md line {line_95}: $95k is not in this run",
        f"narrative.md line {line_95}: $1,234 is not in this run",
    ]
    assert "47.5%" in result.path.read_text()  # a warning, not a refusal


def test_a_dollar_figure_in_the_render_is_not_stale():
    narrative = pub.Narrative({}, {}, ["They pay $85k and $85,000.", "and 33.3 %"])
    assert pub.stale_numbers(narrative, "| $85,000 | 33.3% |") == []


def test_a_second_publish_is_not_stamped_dirty_by_the_first(tmp_path, monkeypatch):
    """The first publish edits README.md and docs/reports/; publishing again after
    fixing the narrative must not mark the stamp's commit "-dirty" for that."""
    from src.reports import provenance

    seen = []

    def fake_git_commit(repo_root=REPO_ROOT, ignore=()):
        seen.append(ignore)
        return "c0ffee000000"

    monkeypatch.setattr(provenance, "git_commit", fake_git_commit)
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    result = pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None)
    assert seen == [pub.PUBLISH_OUTPUTS]
    assert set(pub.PUBLISH_OUTPUTS) == {"docs/reports", "README.md"}
    assert "| Git commit | `c0ffee000000` |" in result.path.read_text()


def test_republishing_replaces_old_charts(tmp_path):
    write_narrative(tmp_path, disclosure.SLUG, GOOD)
    stale = tmp_path / disclosure.SLUG / "old-chart.png"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"x")
    pub.publish(disclosure.SLUG, disc_reader(), tmp_path, None)
    assert not stale.exists()


# --------------------------------------------------------------------- #
# Report 3: the narrative never names an employer next to sponsorship


EMP_GOOD = {
    "Headline": "Invented: FAKE Alpha posts the most commercial roles.",
    "What it means": "Invented: filing records describe employers in aggregate.",
    "What to do about it": "Invented action text.",
}


def emp_reader():
    return FakeReader(t_emp.frames())


def test_report3_publishes_a_narrative_that_names_employers_only_for_hiring(tmp_path):
    write_narrative(tmp_path, employers.SLUG, EMP_GOOD)
    md = pub.publish(employers.SLUG, emp_reader(), tmp_path, None).path.read_text()
    assert "FAKE Alpha posts the most" in md


@pytest.mark.parametrize(
    "paragraph",
    [
        "FAKE Alpha has filed many H-1B LCAs.",
        "fake alpha sponsors visas.",
        "Of the top employers, FAKE Agency A has a certified filing.",
    ],
)
def test_report3_refuses_an_employer_named_in_a_sponsorship_paragraph(tmp_path, paragraph):
    write_narrative(tmp_path, employers.SLUG, dict(EMP_GOOD, **{"What it means": paragraph}))
    with pytest.raises(GuardrailError, match="names"):
        pub.publish(employers.SLUG, emp_reader(), tmp_path, None)


def test_report3_narrative_still_meets_the_sponsorship_wording_rule(tmp_path):
    claim = "Most employers don't sponsor."
    write_narrative(tmp_path, employers.SLUG, dict(EMP_GOOD, **{"What it means": claim}))
    with pytest.raises(GuardrailError, match="can't support"):
        pub.publish(employers.SLUG, emp_reader(), tmp_path, None)


# --------------------------------------------------------------------- #
# B3 README block


def published(docs: Path, slug: str, title: str, when: str, chart: str | None) -> None:
    out = docs / slug
    out.mkdir(parents=True, exist_ok=True)
    image = f"\n\n![Alt for {slug}]({chart})" if chart else ""
    (out / "report.md").write_text(
        f"<!-- c -->\n\n# {title}\n\n| Provenance | |\n|---|---|\n"
        f"| Generated at | {when} UTC |{image}\n\n![second](second.png)\n"
    )


def block(path: Path) -> str:
    text = path.read_text()
    return text[text.index(pub.README_START) : text.index(pub.README_END) + len(pub.README_END)]


def test_readme_block_with_nothing_published(tmp_path):
    docs = tmp_path / "docs" / "reports"
    docs.mkdir(parents=True)
    path = readme(tmp_path)
    assert pub.update_index(path, docs)
    assert block(path) == (
        f"{pub.README_START}\nThe reports are rendered from the SQL views and published here as "
        "each narrative is written; see [docs/reports.md](docs/reports.md).\n"
        f"{pub.README_END}"
    )
    assert path.read_text().startswith("# Title\n\nintro\n\n")
    assert path.read_text().endswith(f"{pub.README_END}\n\n## Next\n")
    assert not pub.update_index(path, docs)  # idempotent


def test_readme_block_with_one_published_report(tmp_path):
    docs = tmp_path / "docs" / "reports"
    published(docs, "a-report", "Report A", "2026-11-01 08:00:00", "lead.png")
    path = readme(tmp_path)
    pub.update_index(path, docs)
    assert block(path) == "\n".join(
        [
            pub.README_START,
            "| Report | Published |",
            "|---|---|",
            "| [Report A](docs/reports/a-report/report.md) | 2026-11-01 |",
            "",
            "![Alt for a-report](docs/reports/a-report/lead.png)",
            pub.README_END,
        ]
    )


def test_readme_block_with_two_lists_newest_first_and_embeds_its_chart(tmp_path):
    docs = tmp_path / "docs" / "reports"
    published(docs, "a-report", "Report A", "2026-11-01 08:00:00", "lead.png")
    published(docs, "b-report", "Report B", "2026-11-05 08:00:00", "b-lead.png")
    path = readme(tmp_path)
    pub.update_index(path, docs)
    text = block(path)
    assert text.index("Report B") < text.index("Report A")
    assert "![Alt for b-report](docs/reports/b-report/b-lead.png)" in text
    assert "a-report/lead.png" not in text


def test_readme_without_markers_is_refused(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# no block\n")
    with pytest.raises(pub.PublishRefused, match="no published-reports block"):
        pub.update_index(path, tmp_path)


def test_publish_refreshes_the_readme_copy(tmp_path):
    docs = tmp_path / "docs" / "reports"
    write_narrative(docs, disclosure.SLUG, GOOD)
    path = readme(tmp_path)
    pub.publish(disclosure.SLUG, disc_reader(), docs, path)
    text = block(path)
    assert f"[{disclosure.TITLE}](docs/reports/{disclosure.SLUG}/report.md)" in text
    assert f"(docs/reports/{disclosure.SLUG}/measured-fields.png)" in text


def test_the_real_readme_has_the_block():
    text = (REPO_ROOT / "README.md").read_text()
    assert text.count(pub.README_START) == 1 and text.count(pub.README_END) == 1


# --------------------------------------------------------------------- #
# end to end on the synthetic demo seed, through the test-only override


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_init_and_publish_on_the_demo_seed(tmp_path, monkeypatch):
    from scripts.seed_demo_data import seed_full
    from src.reports.__main__ import main
    from src.reports.views import ViewReader
    from tests.conftest import reset_schema

    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    docs = tmp_path / "docs" / "reports"
    path = readme(tmp_path)
    try:
        for slug in REPORTS:
            narrative, created = pub.init_narrative(slug, docs)
            assert created
            sections = {s: f"Invented {s.lower()} text for a test." for s in REPORTS[slug].SECTIONS}
            write_narrative(docs, slug, sections)
            result = pub.publish(slug, ViewReader(engine), docs, path, allow_demo=True)
            md = result.path.read_text()
            assert f"> **{DEMO_BANNER}**" in md and "| Database | `jobmarket_test` |" in md
            assert PLACEHOLDER_MARK not in md
        assert block(path).count("| [") == len(REPORTS)

        # the CLI refuses the same database without the override (before reading
        # any narrative, so the real docs/reports/ is never touched)
        monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
        assert main([disclosure.SLUG, "--publish"]) == 1
    finally:
        engine.dispose()
