"""Dashboards as files: load and validate `dashboards/*.json` + `dashboards/sql/*.sql`.

Layout:
  dashboards/<slug>.json   name, description, public (bool), cards[]
  dashboards/sql/<key>.sql one per question card

A card is either
  {"key", "type": "question", "title", "sql", "display", "description",
   "position": {"col", "row"}, "size": {"x", "y"}, "visualization_settings"}
or a text card (headings and caveat notes)
  {"key", "type": "text", "text", "position", "size"}.

`validate()` enforces the project's dashboard rules (the tests in
tests/test_dashboard_spec.py fail on each):
  - card SQL reads only relations named v_* (SQL views are the source of
    truth; the metabase_reader role enforces the same thing at run time)
  - every question card has a description
  - a card reading v_commercial_salary_clean filters salary_is_predicted =
    false or splits by salary_is_predicted (never one blended number); the
    split must name the column in GROUP BY (`GROUP BY 1` isn't resolved)
  - a skills card's description carries the truncation caveat
  - an instrument-limited field is labelled "instrument-limited" in the
    card's title or description
  - cards don't overlap and stay inside the GRID_COLUMNS-wide grid
  - every referenced SQL file exists; card keys are unique across dashboards

`key` is the stable identity the provisioner matches Metabase items by.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DASHBOARDS_DIR = Path(__file__).resolve().parents[2] / "dashboards"

# Metabase v0.64.3.4's desktop dashboard grid (its frontend bundle:
# `{desktop:24,mobile:1}`). Re-check when bumping the pinned image.
GRID_COLUMNS = 24

DISPLAYS = {
    "table",
    "object",
    "bar",
    "row",
    "line",
    "area",
    "combo",
    "pie",
    "scalar",
    "smartscalar",
}

SALARY_VIEW = "v_commercial_salary_clean"
SKILL_VIEWS = {"v_skill_top_by_source", "v_skill_category_composition"}
# Fields the view headers document as measuring our instruments, not the market.
INSTRUMENT_LIMITED_FIELDS = (
    "pct_seniority_present",
    "pct_metro_present",
    "pct_remote_true",
    "seniority",
    "metro_area",
)
INSTRUMENT_LABEL = "instrument-limited"


@dataclass
class Card:
    key: str
    type: str  # "question" | "text"
    col: int
    row: int
    width: int
    height: int
    title: str = ""
    sql_file: str | None = None
    display: str | None = None
    description: str = ""
    text: str = ""
    visualization_settings: dict = field(default_factory=dict)

    @property
    def is_question(self) -> bool:
        return self.type == "question"


@dataclass
class Dashboard:
    slug: str
    name: str
    description: str
    public: bool
    cards: list[Card]


class SpecError(ValueError):
    """The spec files are malformed or break a dashboard rule."""


def _card(raw: dict) -> Card:
    pos, size = raw.get("position") or {}, raw.get("size") or {}
    return Card(
        key=raw.get("key", ""),
        type=raw.get("type", "question"),
        col=int(pos.get("col", -1)),
        row=int(pos.get("row", -1)),
        width=int(size.get("x", 0)),
        height=int(size.get("y", 0)),
        title=raw.get("title", ""),
        sql_file=raw.get("sql"),
        display=raw.get("display"),
        description=raw.get("description", ""),
        text=raw.get("text", ""),
        visualization_settings=raw.get("visualization_settings") or {},
    )


def load_dashboards(directory: Path = DASHBOARDS_DIR) -> list[Dashboard]:
    dashboards = []
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text())
        dashboards.append(
            Dashboard(
                slug=path.stem,
                name=raw.get("name", ""),
                description=raw.get("description", ""),
                public=bool(raw.get("public", False)),
                cards=[_card(c) for c in raw.get("cards", [])],
            )
        )
    return dashboards


def card_sql(card: Card, directory: Path = DASHBOARDS_DIR) -> str:
    return (directory / "sql" / card.sql_file).read_text()


# --------------------------------------------------------------------- #
# SQL inspection (static; the reader role is the run-time enforcement)

_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_STRING = re.compile(r"'(?:[^']|'')*'")
_IDENT = r'(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?'
_FROM_JOIN = re.compile(r"\b(?:from|join)\b", re.I)
_CTE = re.compile(r"(?:\bwith\b(?:\s+recursive)?|,)\s*([A-Za-z_]\w*)\s+as\s*\(", re.I)
# FROM inside these calls is part of the function's syntax, not a relation.
_FROM_FUNCTIONS = {"extract", "substring", "trim", "overlay", "position"}


def strip_sql(sql: str) -> str:
    """SQL without comments and string literals (replaced by '')."""
    return _STRING.sub("''", _COMMENT.sub(" ", sql))


def _enclosing_function(sql: str, pos: int) -> str | None:
    depth = 0
    for i in range(pos - 1, -1, -1):
        if sql[i] == ")":
            depth += 1
        elif sql[i] == "(":
            if depth == 0:
                m = re.search(r"([A-Za-z_]\w*)\s*$", sql[:i])
                return m.group(1).lower() if m else None
            depth -= 1
    return None


def _skip_parens(sql: str, pos: int) -> int:
    """Position just past the ")" closing an already-opened "(" (pos is inside it)."""
    depth = 1
    while pos < len(sql) and depth:
        depth += {"(": 1, ")": -1}.get(sql[pos], 0)
        pos += 1
    return pos


def _bare(name: str) -> str:
    """Last dotted part, unquoted, lowercased: public."V_X" -> v_x."""
    return name.split(".")[-1].strip().strip('"').lower()


def referenced_relations(sql: str) -> set[str]:
    """Relations named after FROM/JOIN (and in FROM comma lists), minus CTE
    names, subqueries and set-returning function calls."""
    sql = strip_sql(sql)
    ctes = {m.group(1).lower() for m in _CTE.finditer(sql)}
    found: set[str] = set()
    for m in _FROM_JOIN.finditer(sql):
        if _enclosing_function(sql, m.start()) in _FROM_FUNCTIONS:
            continue
        pos = m.end()
        while True:
            item = re.match(rf"\s*(?:lateral\s+)?({_IDENT})(\s*\()?", sql[pos:], re.I)
            if not item:  # a subquery "(": its own FROM is matched separately
                break
            pos += item.end()
            if item.group(2):  # a function call like generate_series(...): not a relation
                pos = _skip_parens(sql, pos)
            else:
                name = _bare(item.group(1))
                if name not in ctes:
                    found.add(name)
            # optional alias, then a comma continues the FROM list
            alias = re.match(r"\s+(?:as\s+)?(?!on\b|where\b|group\b|order\b|join\b|left\b|"
                             r"right\b|inner\b|full\b|cross\b|limit\b|union\b)[A-Za-z_]\w*",
                             sql[pos:], re.I)  # fmt: skip
            if alias:
                pos += alias.end()
            comma = re.match(r"\s*,", sql[pos:])
            if not comma:
                break
            pos += comma.end()
    return found


def _mentions(sql: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", sql, re.I) is not None


def splits_or_filters_predicted(sql: str) -> bool:
    s = re.sub(r"\s+", " ", strip_sql(sql)).lower()
    filters = re.search(r"\bsalary_is_predicted\s*=\s*false\b", s) or re.search(
        r"\bnot\s+salary_is_predicted\b", s
    )
    splits = re.search(r"\bgroup by\b[^;]*\bsalary_is_predicted\b", s)
    return bool(filters or splits)


def has_truncation_caveat(description: str) -> bool:
    d = description.lower()
    return "truncat" in d and "500" in d


# --------------------------------------------------------------------- #


def _overlaps(a: Card, b: Card) -> bool:
    return (
        a.col < b.col + b.width
        and b.col < a.col + a.width
        and a.row < b.row + b.height
        and b.row < a.row + a.height
    )


def validate(dashboards: list[Dashboard], directory: Path = DASHBOARDS_DIR) -> list[str]:
    """Every rule violation as a readable line; empty means valid."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for dash in dashboards:
        where = f"{dash.slug}"
        if not dash.name:
            errors.append(f"{where}: dashboard has no name")
        for card in dash.cards:
            at = f"{where}/{card.key or '?'}"
            if not card.key:
                errors.append(f"{at}: card has no key")
            elif card.key in seen:
                errors.append(f"{at}: duplicate card key (also in {seen[card.key]})")
            else:
                seen[card.key] = dash.slug

            if card.width <= 0 or card.height <= 0 or card.col < 0 or card.row < 0:
                errors.append(f"{at}: invalid grid position/size")
            elif card.col + card.width > GRID_COLUMNS:
                errors.append(
                    f"{at}: runs off the {GRID_COLUMNS}-column grid "
                    f"(col {card.col} + width {card.width})"
                )

            if card.type == "text":
                if not card.text.strip():
                    errors.append(f"{at}: text card has no text")
                continue
            if card.type != "question":
                errors.append(f"{at}: unknown card type {card.type!r}")
                continue

            if not card.title:
                errors.append(f"{at}: card has no title")
            if not card.description.strip():
                errors.append(f"{at}: card has no description")
            if card.display not in DISPLAYS:
                errors.append(f"{at}: unknown display {card.display!r}")
            if not card.sql_file or not (directory / "sql" / card.sql_file).is_file():
                errors.append(f"{at}: missing SQL file {card.sql_file!r}")
                continue

            sql = card_sql(card, directory)
            relations = referenced_relations(sql)
            for rel in sorted(r for r in relations if not r.startswith("v_")):
                errors.append(f"{at}: reads {rel!r}; cards may read v_* views only")
            if SALARY_VIEW in relations and not splits_or_filters_predicted(sql):
                errors.append(
                    f"{at}: reads {SALARY_VIEW} without filtering salary_is_predicted = false "
                    "or splitting by salary_is_predicted"
                )
            if relations & SKILL_VIEWS and not has_truncation_caveat(card.description):
                errors.append(
                    f"{at}: skills card description lacks the ~500-character truncation caveat"
                )
            label_text = f"{card.title} {card.description}".lower()
            body = strip_sql(sql)
            for fld in INSTRUMENT_LIMITED_FIELDS:
                if _mentions(body, fld) and INSTRUMENT_LABEL not in label_text:
                    errors.append(f"{at}: uses {fld} without labelling it {INSTRUMENT_LABEL}")
                    break

        for i, a in enumerate(dash.cards):
            for b in dash.cards[i + 1 :]:
                if _overlaps(a, b):
                    errors.append(f"{where}: cards {a.key!r} and {b.key!r} overlap")
    return errors


def load_and_validate(directory: Path = DASHBOARDS_DIR) -> list[Dashboard]:
    dashboards = load_dashboards(directory)
    errors = validate(dashboards, directory)
    if errors:
        raise SpecError("dashboard spec errors:\n  " + "\n  ".join(errors))
    return dashboards
