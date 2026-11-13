"""The docs describe the repo as it is.

Three checks, no database:

- every view file in sql/views/ has its own entry in docs/data_dictionary.md
  (a heading or a table row that starts with the view's name);
- every `make <target>` that README.md or docs/ shows as a command is a
  target in the Makefile (docs/dev-log/ is left out: it holds work logs
  that are kept as written);
- every relative link and image in README.md and docs/ points at a file
  or directory that exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```.*?^```", re.M | re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
MAKE_CMD = re.compile(r"\bmake ([a-z][a-z0-9_-]*)")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def doc_files() -> list[Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]


def current_doc_files() -> list[Path]:
    """The docs a reader follows today: everything but the work logs."""
    return [p for p in doc_files() if "dev-log" not in p.relative_to(ROOT).parts]


def view_names() -> list[str]:
    return sorted(p.stem for p in (ROOT / "sql" / "views").glob("v_*.sql"))


def described_views(text: str) -> set[str]:
    """View names with a heading or a table row of their own."""
    heading = re.findall(r"^#+ `(v_[a-z0-9_]+)`", text, re.M)
    row = re.findall(r"^\| `(v_[a-z0-9_]+)` \|", text, re.M)
    return set(heading) | set(row)


def make_targets(makefile: str) -> set[str]:
    return set(re.findall(r"^([A-Za-z][A-Za-z0-9_-]*):", makefile, re.M))


def make_commands(text: str) -> set[str]:
    """Targets of `make X` written as a command: in inline code or a fenced block."""
    found: set[str] = set()
    for block in FENCE.findall(text):
        found.update(MAKE_CMD.findall(block))
    for span in INLINE_CODE.findall(FENCE.sub("", text)):
        found.update(MAKE_CMD.findall(span))
    return found


def broken_links(path: Path) -> list[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    text = INLINE_CODE.sub("", text)
    broken = []
    for target in LINK.findall(text):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|#", target):
            continue  # a URL, mailto:, or an anchor in the same file
        file_part = target.split("#", 1)[0]
        if not (path.parent / file_part).exists():
            broken.append(target)
    return broken


# --- the helpers themselves ---------------------------------------------------


def test_described_views_needs_a_heading_or_a_row_of_its_own():
    text = "### `v_a` — x\n| `v_b` | y |\nsee `v_c` for more\n"
    assert described_views(text) == {"v_a", "v_b"}


def test_make_commands_reads_code_only():
    text = "Run `make views`, or make the tea.\n```powershell\nuv run x  # or: make bi-up\n```\n"
    assert make_commands(text) == {"views", "bi-up"}


def test_broken_links_ignores_urls_anchors_and_code(tmp_path):
    (tmp_path / "there.md").write_text("x", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text(
        "[a](there.md#part) [b](https://example.com) [c](#top) [d](missing.md)\n"
        "`[e](also-missing.md)`\n```\n[f](missing-too.md)\n```\n",
        encoding="utf-8",
    )
    assert broken_links(doc) == ["missing.md"]


# --- the repo ----------------------------------------------------------------


def test_every_view_has_a_data_dictionary_entry():
    text = (ROOT / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    missing = sorted(set(view_names()) - described_views(text))
    assert not missing, f"no entry in docs/data_dictionary.md for: {missing}"


def test_every_make_command_in_the_docs_is_a_makefile_target():
    targets = make_targets((ROOT / "Makefile").read_text(encoding="utf-8"))
    unknown = {
        f"{path.relative_to(ROOT)}: make {cmd}"
        for path in current_doc_files()
        for cmd in make_commands(path.read_text(encoding="utf-8"))
        if cmd not in targets
    }
    assert not unknown, sorted(unknown)


@pytest.mark.parametrize("path", doc_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path):
    assert broken_links(path) == []
