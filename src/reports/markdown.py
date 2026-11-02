"""Markdown output that only accepts guardrail-safe numbers.

A table cell is a label (str), an int (a count), None ("—"), or one of the
guardrail types (Count, Rate, Ratio, Stat, Gap, SalarySummary, FlooredSalary,
SalaryDiff). A float, or a label that is really a bare number ("33.8%",
"1,483"), is refused: wrap it so it carries its n or denominator. A table holding a truncation-floored
rate must say "truncation-floored" in its caption or a header.

Narrative sections the owner writes are `placeholder` blocks marked
`[TO WRITE: ...]`, each followed by the numbers from this run to draw on.
"""

from __future__ import annotations

import numbers
import re
from dataclasses import dataclass, field

from src.reports.guardrails import (
    TRUNCATION_LABEL,
    Count,
    FlooredSalary,
    Gap,
    GuardrailError,
    Rate,
    Ratio,
    SalaryDiff,
    SalarySummary,
    Stat,
)
from src.reports.lca_guardrails import FilingCount, FilingWage
from src.reports.provenance import DEMO_BANNER, Provenance

PLACEHOLDER_MARK = "TO WRITE"
_GUARDED = (
    Count,
    Rate,
    Ratio,
    Stat,
    Gap,
    SalarySummary,
    FlooredSalary,
    SalaryDiff,
    FilingCount,
    FilingWage,
)
_BARE_NUMBER = re.compile(r"^\s*[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|pp|x)?\s*$")


def render_cell(cell, row: list | None = None) -> str:
    """One cell. `row` is the table row it sits in (needed for a compact Gap)."""
    if cell is None:
        return "—"
    if isinstance(cell, bool):
        raise GuardrailError(f"boolean {cell!r} in a table: render it as a label")
    if isinstance(cell, numbers.Integral):
        return Count(cell).render()
    if isinstance(cell, Gap) and cell.compact:
        if row is None or not any(c is cell.a or c == cell.a for c in row if isinstance(c, Rate)):
            raise GuardrailError("a compact gap must sit in a table row that shows both its rates")
        if not any(c is cell.b or c == cell.b for c in row if isinstance(c, Rate)):
            raise GuardrailError("a compact gap must sit in a table row that shows both its rates")
        return cell.render()
    if isinstance(cell, _GUARDED):
        return cell.render()
    if isinstance(cell, numbers.Real):
        raise GuardrailError(
            f"bare number {cell!r}: wrap it in Rate, Stat or Ratio so its n travels with it"
        )
    if isinstance(cell, str):
        if _BARE_NUMBER.match(cell):
            raise GuardrailError(
                f"label {cell!r} is a bare number: use a guardrail type so its n travels with it"
            )
        return cell.replace("|", "\\|").replace("\n", " ")
    raise GuardrailError(f"can't render {type(cell).__name__} in a report table")


def _truncation_floored(cell) -> bool:
    return getattr(cell, "truncation_floored", False)


@dataclass
class Doc:
    title: str
    provenance: Provenance
    slug: str
    subtitle: str = ""
    blocks: list[str] = field(default_factory=list)

    def heading(self, text: str, level: int = 2) -> None:
        self.blocks.append(f"{'#' * level} {text}")

    def paragraph(self, text: str) -> None:
        self.blocks.append(text)

    def bullets(self, items: list) -> None:
        """Each item is a str, or (label, cell) rendered as "label: value"."""
        lines = []
        for item in items:
            if isinstance(item, tuple):
                label, cell = item
                lines.append(f"- {label}: {render_cell(cell)}")
            else:
                lines.append(f"- {item}")
        self.blocks.append("\n".join(lines))

    def table(self, headers: list[str], rows: list[list], caption: str = "") -> None:
        if any(len(row) != len(headers) for row in rows):
            raise GuardrailError("table row length doesn't match its headers")
        floored = any(_truncation_floored(c) for row in rows for c in row)
        labelled = TRUNCATION_LABEL in caption or any(TRUNCATION_LABEL in h for h in headers)
        if floored and not labelled:
            raise GuardrailError(
                f"table holds commercial skill rates but doesn't say {TRUNCATION_LABEL!r} "
                "in its caption or headers"
            )
        lines = []
        if caption:
            lines += [caption, ""]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            lines.append("| " + " | ".join(render_cell(c, row) for c in row) + " |")
        self.blocks.append("\n".join(lines))

    def image(self, filename: str, alt: str) -> None:
        self.blocks.append(f"![{alt}]({filename})")

    def placeholder(self, section: str, prompt: str, numbers_: list[tuple[str, object]]) -> None:
        """A section the owner writes, with this run's relevant numbers beside it."""
        floored = any(_truncation_floored(cell) for _, cell in numbers_)
        lines = [f"> **[{PLACEHOLDER_MARK}: {section}]** {prompt}", ">"]
        lines.append("> Numbers from this run to draw on:")
        lines += [f"> - {label}: {render_cell(cell)}" for label, cell in numbers_]
        if floored:
            lines.append(f"> - (commercial skill rates are {TRUNCATION_LABEL})")
        self.blocks.append("\n".join(lines))

    def render(self) -> str:
        p = self.provenance
        head = [
            f"<!-- Generated by `python -m src.reports {self.slug}`. Every table, chart and "
            "number is recomputed from the SQL views on each run, and the file is overwritten: "
            f"write narrative in a copy (docs/reports.md). -->",
        ]
        if p.is_demo:
            head.append(f"> **{DEMO_BANNER}**")
        head.append(f"# {self.title}")
        if self.subtitle:
            head.append(f"_{self.subtitle}_")
        stamp = [
            "| Provenance | |",
            "|---|---|",
            f"| Database | `{p.database}` |",
            f"| Generated at | {p.generated_at:%Y-%m-%d %H:%M:%S} UTC |",
            f"| Git commit | `{p.git_commit}` |",
        ]
        stamp += [f"| Rows in `{view}` | {rows:,} |" for view, rows in p.view_rows.items()]
        head.append("\n".join(stamp))
        return "\n\n".join(head + self.blocks) + "\n"
