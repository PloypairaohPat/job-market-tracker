"""From "rendered" to "published in the repo": narrative files, publish, index.

A report's narrative lives in docs/reports/<slug>/narrative.md, written and
committed by the owner, with one `##` heading per placeholder section of the
report (the module's SECTIONS). Three operations:

- `init_narrative` writes that file with the headings and, under each, an
  HTML comment saying what the section is for and where its numbers are.
  It never overwrites an existing file.
- `publish` renders the report from the views with the narrative merged in
  place of each `[TO WRITE: ...]` block (the "numbers from this run" lists
  are left out) and writes docs/reports/<slug>/report.md plus its PNGs. It
  refuses a demo/test database, a missing or unfinished narrative, and any
  guardrail failure, and warns about narrative figures this run's render
  doesn't contain.
- `update_index` rewrites the block between README_START and README_END in
  README.md: one row per published report, and the lead chart of the most
  recent one.

Nothing here writes narrative: every sentence of a published report's
narrative comes from the owner's narrative.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType

from src.reports.catalog import REPORTS
from src.reports.guardrails import GuardrailError
from src.reports.markdown import PLACEHOLDER_MARK
from src.reports.provenance import DEMO_BANNER, REPO_ROOT, Provenance, is_demo_database
from src.reports.views import ViewReader

DOCS_REPORTS = REPO_ROOT / "docs" / "reports"
README = REPO_ROOT / "README.md"
README_START = "<!-- published-reports:start -->"
README_END = "<!-- published-reports:end -->"
INIT_COMMENT_TAG = "init-narrative:"
# Tracked files that publishing writes; their changes don't make the stamp "-dirty".
PUBLISH_OUTPUTS = ("docs/reports", "README.md")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_BLOCK = re.compile(rf"^> \*\*\[{PLACEHOLDER_MARK}: (?P<section>[^\]]+)\]\*\*")
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")
_DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?\b")


class PublishRefused(Exception):
    """Publishing stopped for a stated reason; nothing was written."""


@dataclass
class PublishResult:
    path: Path
    charts: list[str]
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- #
# narrative files


def narrative_path(slug: str, docs_dir: Path = DOCS_REPORTS) -> Path:
    return docs_dir / slug / "narrative.md"


def sections_of(slug: str) -> dict[str, str]:
    return dict(REPORTS[slug].SECTIONS)


def init_narrative(slug: str, docs_dir: Path = DOCS_REPORTS) -> tuple[Path, bool]:
    """Create the narrative template. Returns (path, created); never overwrites."""
    path = narrative_path(slug, docs_dir)
    if path.exists():
        return path, False
    module = REPORTS[slug]
    views = ", ".join(f"`{v}`" for v in module.VIEWS)
    lines = [
        f"# {module.TITLE}: narrative",
        "",
        "<!-- "
        f"{INIT_COMMENT_TAG} one `##` section per placeholder in the report. Write each "
        f"section below its heading, then run `python -m src.reports {slug} --publish`. HTML "
        "comments like this one are dropped when publishing. -->",
    ]
    for section, purpose in module.SECTIONS.items():
        lines += [
            "",
            f"## {section}",
            "",
            "<!-- "
            f"{INIT_COMMENT_TAG} {purpose} Numbers: render the report "
            f"(`python -m src.reports {slug}`) and use the list under "
            f"'[{PLACEHOLDER_MARK}: {section}]' in reports/{slug}/report.md. Every figure "
            f"there comes from the views {views}. -->",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, True


@dataclass(frozen=True)
class Narrative:
    sections: dict[str, str]  # heading -> text with HTML comments removed
    line_of: dict[str, int]  # heading -> line number (1-based) of the heading
    raw_lines: list[str]


def read_narrative(slug: str, docs_dir: Path = DOCS_REPORTS) -> Narrative:
    """Parse and validate narrative.md. Raises PublishRefused naming the reason."""
    path = narrative_path(slug, docs_dir)
    if not path.exists():
        raise PublishRefused(
            f"{path} doesn't exist. Create it with `python -m src.reports {slug} "
            "--init-narrative`, write each section, then publish."
        )
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    sections: dict[str, list[str]] = {}
    line_of: dict[str, int] = {}
    current: str | None = None
    for i, line in enumerate(lines, start=1):
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                raise PublishRefused(f"{path}: section {current!r} appears twice")
            sections[current] = []
            line_of[current] = i
        elif current is not None:
            sections[current].append(line)
    expected = sections_of(slug)
    unknown = [s for s in sections if s not in expected]
    if unknown:
        raise PublishRefused(
            f"{path}: unknown section(s) {unknown}; the report's sections are {list(expected)}"
        )
    missing = [s for s in expected if s not in sections]
    if missing:
        raise PublishRefused(f"{path}: missing section(s) {missing}")
    cleaned: dict[str, str] = {}
    for section in expected:
        body = "\n".join(sections[section])
        if PLACEHOLDER_MARK in body:
            raise PublishRefused(
                f"{path}: section {section!r} still contains the placeholder mark "
                f"{PLACEHOLDER_MARK!r}"
            )
        text = _COMMENT.sub("", body).strip()
        if not text:
            what = "holds only the init comment" if INIT_COMMENT_TAG in body else "is empty"
            raise PublishRefused(f"{path}: section {section!r} {what}")
        cleaned[section] = text
    return Narrative(cleaned, line_of, lines)


# --------------------------------------------------------------------- #
# merge + checks


def merge(rendered: str, narrative: Narrative, slug: str) -> str:
    """Replace each placeholder block with its narrative, and the generated-by
    comment with a published-by one. The provenance stamp is kept."""
    blocks = rendered.rstrip("\n").split("\n\n")
    out: list[str] = []
    seen: list[str] = []
    for block in blocks:
        m = _PLACEHOLDER_BLOCK.match(block)
        if m:
            section = m.group("section")
            if section not in narrative.sections:
                raise PublishRefused(f"the render has a section {section!r} the narrative lacks")
            out.append(narrative.sections[section])
            seen.append(section)
        elif block.startswith("<!-- Generated by `python -m src.reports"):
            out.append(
                f"<!-- Published by `python -m src.reports {slug} --publish`. Tables, charts and "
                "numbers are recomputed from the SQL views; the narrative sections come from "
                f"docs/reports/{slug}/narrative.md. Edit that file and publish again rather than "
                "editing this one. -->"
            )
        else:
            out.append(block)
    unused = [s for s in narrative.sections if s not in seen]
    if unused:
        raise PublishRefused(f"the render has no placeholder for section(s) {unused}")
    text = "\n\n".join(out) + "\n"
    if PLACEHOLDER_MARK in text:
        raise PublishRefused(f"the published text still contains {PLACEHOLDER_MARK!r}")
    return text


def _dollar_value(number: str, suffix: str | None) -> float:
    value = float(number.replace(",", ""))
    if suffix:
        value *= 1_000 if suffix.lower() == "k" else 1_000_000
    return value


def stale_numbers(narrative: Narrative, rendered: str) -> list[str]:
    """Narrative percentages and dollar figures that this run's render doesn't
    contain, each with its line number in narrative.md."""
    percents = {float(m.group(1)) for m in _PERCENT.finditer(rendered)}
    dollars = {_dollar_value(m.group(1), m.group(2)) for m in _DOLLARS.finditer(rendered)}
    warnings = []
    in_comment = False
    for i, line in enumerate(narrative.raw_lines, start=1):
        # skip HTML comments, which can span lines
        visible = ""
        rest = line
        while rest:
            if in_comment:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                else:
                    in_comment, rest = False, rest[end + 3 :]
            else:
                start = rest.find("<!--")
                if start < 0:
                    visible, rest = visible + rest, ""
                else:
                    visible, rest, in_comment = visible + rest[:start], rest[start + 4 :], True
        for m in _PERCENT.finditer(visible):
            if float(m.group(1)) not in percents:
                warnings.append(f"narrative.md line {i}: {m.group(0).strip()} is not in this run")
        for m in _DOLLARS.finditer(visible):
            if _dollar_value(m.group(1), m.group(2)) not in dollars:
                warnings.append(f"narrative.md line {i}: {m.group(0).strip()} is not in this run")
    return warnings


def uncommitted_report_inputs(repo_root: Path = REPO_ROOT) -> list[str]:
    """Tracked files under sql/views/ or src/reports/ with uncommitted changes."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", "sql/views", "src/reports"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line[3:] for line in out.splitlines() if line.strip()]


# --------------------------------------------------------------------- #
# publish


def publish(
    slug: str,
    reader: ViewReader,
    docs_dir: Path = DOCS_REPORTS,
    readme: Path | None = README,
    *,
    allow_demo: bool = False,
) -> PublishResult:
    """Render `slug` with its narrative merged in and write it under docs_dir.

    `allow_demo` exists for tests only (the CLI never sets it): it lets the
    path run on a demo/test database, and the published file keeps the demo
    banner.
    """
    module: ModuleType = REPORTS[slug]
    database = reader.database_name()
    if is_demo_database(database) and not allow_demo:
        raise PublishRefused(
            f"database {database!r} is a demo/test database (its name contains 'demo' or "
            "'test'): synthetic numbers are never published as findings"
        )
    narrative = read_narrative(slug, docs_dir)

    frames = {view: reader.read(view) for view in module.VIEWS}
    data = module.compute(frames)
    provenance = Provenance.collect(database, reader.rows_read, ignore_dirty=PUBLISH_OUTPUTS)
    with tempfile.TemporaryDirectory() as tmp:
        rendered_path = module.render(data, provenance, Path(tmp))  # guardrails run here
        rendered = rendered_path.read_text(encoding="utf-8")
        text = merge(rendered, narrative, slug)
        check = getattr(module, "check_published", None)
        if check is not None:
            check(data, narrative.sections, text)
        if provenance.is_demo and DEMO_BANNER not in text:
            raise GuardrailError("a report published from a demo database lost its banner")
        warnings = stale_numbers(narrative, rendered)

        out = docs_dir / slug
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.png"):
            old.unlink()
        charts = []
        for png in sorted(rendered_path.parent.glob("*.png")):
            shutil.copy2(png, out / png.name)
            charts.append(png.name)
        path = out / "report.md"
        path.write_text(text, encoding="utf-8")
    if readme is not None:
        update_index(readme, docs_dir)
    return PublishResult(path, charts, warnings)


# --------------------------------------------------------------------- #
# README index


@dataclass(frozen=True)
class Published:
    slug: str
    title: str
    published_at: datetime
    lead_chart: str | None
    lead_alt: str


_TITLE = re.compile(r"^# (.+)$", re.MULTILINE)
_GENERATED = re.compile(r"^\| Generated at \| (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC \|$", re.M)
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+\.png)\)$", re.MULTILINE)


def published_reports(docs_dir: Path = DOCS_REPORTS) -> list[Published]:
    """Every docs/reports/<slug>/report.md, newest first."""
    found = []
    for path in sorted(docs_dir.glob("*/report.md")):
        text = path.read_text(encoding="utf-8")
        title = _TITLE.search(text)
        stamp = _GENERATED.search(text)
        if not title or not stamp:
            continue
        image = _IMAGE.search(text)
        found.append(
            Published(
                slug=path.parent.name,
                title=title.group(1).strip(),
                published_at=datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S"),
                lead_chart=image.group(2) if image else None,
                lead_alt=image.group(1) if image else "",
            )
        )
    return sorted(found, key=lambda p: (p.published_at, p.slug), reverse=True)


def index_block(reports: list[Published], docs_dir: Path, readme: Path) -> str:
    """The README block (markers included) for these published reports."""
    base = Path(_relpath(docs_dir, readme.parent))
    if not reports:
        body = (
            "The reports are rendered from the SQL views and published here as each "
            "narrative is written; see [docs/reports.md](docs/reports.md)."
        )
    else:
        lines = ["| Report | Published |", "|---|---|"]
        for r in reports:
            link = (base / r.slug / "report.md").as_posix()
            lines.append(f"| [{r.title}]({link}) | {r.published_at:%Y-%m-%d} |")
        latest = reports[0]
        if latest.lead_chart:
            chart = (base / latest.slug / latest.lead_chart).as_posix()
            lines += ["", f"![{latest.lead_alt}]({chart})"]
        body = "\n".join(lines)
    return f"{README_START}\n{body}\n{README_END}"


def _relpath(target: Path, start: Path) -> str:
    import os

    return os.path.relpath(target.resolve(), start.resolve())


def update_index(readme: Path = README, docs_dir: Path = DOCS_REPORTS) -> bool:
    """Rewrite the README block. Returns whether the file changed."""
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(README_START), text.find(README_END)
    if start < 0 or end < start:
        raise PublishRefused(
            f"{readme} has no published-reports block ({README_START} ... {README_END})"
        )
    block = index_block(published_reports(docs_dir), docs_dir, readme)
    new = text[:start] + block + text[end + len(README_END) :]
    if new == text:
        return False
    readme.write_text(new, encoding="utf-8")
    return True
