"""Promote approved match-review pairs into company_aliases.json, safely.

Run:  python -m src.cleaning.aliases apply --from data/sponsor_match_candidates.csv
      python -m src.cleaning.aliases apply --from data/company_merge_candidates.csv --write

Either candidate CSV works; its header says which it is:
  - data/company_merge_candidates.csv (apply_cleaning --only companies):
    name_a, name_b, relation, similarity, approved
  - data/sponsor_match_candidates.csv (python -m src.visa.sponsor_match):
    company_key, lca_employer_key, relation, similarity, approved

Only rows whose `approved` is y, yes, x, 1 or true (any case, trimmed) are
read. Which key survives: an optional keep_a / keep_b column (keep_company /
keep_lca for the sponsor CSV) marks it; otherwise the longer key is mapped
onto the shorter one, alphabetical order breaking a tie (parked default).

Every pair is checked, and a row that fails is refused with its reason:
  - both keys non-empty, not starting with "_", and already the key the
    normalizer's rules produce
  - no self-map
  - no conflict: a key already mapped elsewhere stays as it is
  - no chain: a target that is itself an alias resolves to its final key,
    and a key that other aliases point to can't be mapped away
  - no cycle
Rows are checked in order against the file plus the rows accepted before
them, so a second run with the same CSV adds nothing.

The default is a DRY RUN: it prints the rows it would add, the refused rows
with their reasons, and the resulting diff of the JSON. `--write` writes the
file, keeping `_meta`, every `_comment_*` entry and the existing order,
appending the new keys sorted, as UTF-8 with the file's own indent and a
trailing newline; then it prints the commands to run next. It never runs
them itself.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.cleaning.company_normalizer import ALIASES_PATH, rule_key

APPROVED = {"y", "yes", "x", "1", "true"}
LAYOUTS = {
    # header pair -> (column a, column b, keep column for a, keep column for b)
    "company merge candidates": ("name_a", "name_b", "keep_a", "keep_b"),
    "sponsor match candidates": ("company_key", "lca_employer_key", "keep_company", "keep_lca"),
}
FOLLOW_UP = (
    "uv run python -m src.cleaning.apply_cleaning --only companies",
    "uv run python -m src.visa.lca_loader --rekey",
    "uv run python scripts/apply_views.py",
    "uv run python -m src.reports employers-and-sponsorship",
)


class CandidateFileError(ValueError):
    """The CSV isn't one of the two candidate files."""


@dataclass
class Plan:
    layout: str
    added: list[tuple[int, str, str]] = field(default_factory=list)  # (line, key, target)
    already: list[tuple[int, str, str]] = field(default_factory=list)
    refused: list[tuple[int, str, str, str]] = field(default_factory=list)  # (line, a, b, why)
    n_unapproved: int = 0


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in APPROVED


def read_candidates(path: Path) -> tuple[str, list[tuple[int, dict[str, str]]]]:
    """(layout name, [(line number, row)]) for every row of the CSV."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or ())
        for name, (col_a, col_b, *_) in LAYOUTS.items():
            if {col_a, col_b, "approved"} <= header:
                return name, [(i, row) for i, row in enumerate(reader, start=2)]
    raise CandidateFileError(
        f"{path.name}: not a candidate CSV. Expected the columns name_a, name_b, approved "
        "(company_merge_candidates.csv) or company_key, lca_employer_key, approved "
        "(sponsor_match_candidates.csv)"
    )


def default_direction(a: str, b: str) -> tuple[str, str]:
    """(key that's mapped away, key that survives): the longer onto the shorter,
    alphabetical order breaking a tie."""
    survivor = min(a, b, key=lambda k: (len(k), k))
    return (b if survivor == a else a), survivor


def _resolve(key: str, aliases: dict[str, str]) -> str:
    seen = {key}
    while key in aliases:
        key = aliases[key]
        if key in seen:
            break  # an existing cycle; the cycle check reports it
        seen.add(key)
    return key


def plan(rows: list[tuple[int, dict[str, str]]], layout: str, aliases: dict[str, str]) -> Plan:
    """Check every approved row against `aliases` plus the rows accepted so far."""
    col_a, col_b, keep_a, keep_b = LAYOUTS[layout]
    working = {k: v for k, v in aliases.items() if not k.startswith("_comment")}
    result = Plan(layout)
    for line, row in rows:
        if not _truthy(row.get("approved")):
            result.n_unapproved += 1
            continue
        a, b = (row.get(col_a) or "").strip(), (row.get(col_b) or "").strip()

        def refuse(why: str, a=a, b=b, line=line) -> None:
            result.refused.append((line, a, b, why))

        if not a or not b:
            refuse("a key is empty")
            continue
        if a.startswith("_") or b.startswith("_"):
            refuse("keys starting with '_' are reserved for _meta and _comment_ entries")
            continue
        bad = [k for k in (a, b) if rule_key(k) != k]
        if bad:
            refuse(
                "not a normalized key: " + "; ".join(f"{k!r} would be {rule_key(k)!r}" for k in bad)
            )
            continue
        if a == b:
            refuse("maps a key onto itself")
            continue
        keeps = (_truthy(row.get(keep_a)), _truthy(row.get(keep_b)))
        if all(keeps):
            refuse(f"both {keep_a} and {keep_b} are marked: keep one")
            continue
        if keeps[0]:
            source, target = b, a
        elif keeps[1]:
            source, target = a, b
        else:
            source, target = default_direction(a, b)

        final = _resolve(target, working)
        if final == source:
            refuse(f"would create a cycle: {target!r} already resolves to {source!r}")
            continue
        if source in working:
            if _resolve(source, working) == final:
                result.already.append((line, source, final))
            else:
                refuse(
                    f"conflict: {source!r} is already mapped to {working[source]!r}; "
                    "change or remove that alias by hand first"
                )
            continue
        pointing = sorted(k for k, v in working.items() if v == source)
        if pointing:
            refuse(
                f"would make a chain: {', '.join(map(repr, pointing))} already map to {source!r}; "
                f"keep {source!r} instead (mark {keep_a if source == b else keep_b})"
            )
            continue
        working[source] = final
        result.added.append((line, source, final))
    return result


def _indent(text: str) -> int:
    found = re.search(r"\n( +)\S", text)
    return len(found.group(1)) if found else 2


def render_file(original: str, added: list[tuple[int, str, str]]) -> str:
    """The file with the new aliases appended (sorted), everything else kept."""
    data = json.loads(original)
    for _, key, target in sorted(added, key=lambda t: t[1]):
        data["aliases"][key] = target
    return json.dumps(data, indent=_indent(original), ensure_ascii=False) + "\n"


def diff(original: str, updated: str, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"{name} (now)",
            tofile=f"{name} (after --write)",
        )
    )


def apply(csv_path: Path, aliases_path: Path = ALIASES_PATH, write: bool = False) -> Plan:
    layout, rows = read_candidates(csv_path)
    original = aliases_path.read_text(encoding="utf-8")
    result = plan(rows, layout, json.loads(original)["aliases"])
    updated = render_file(original, result.added)

    print(f"{csv_path.name}: {layout}; {len(rows)} row(s), {result.n_unapproved} not approved")
    print(
        f"would add {len(result.added)} alias(es):"
        if not write
        else f"adding {len(result.added)} alias(es):"
    )
    for line, key, target in result.added:
        print(f"  line {line}: {key!r} -> {target!r}")
    if result.already:
        print(f"already in the file ({len(result.already)}):")
        for line, key, target in result.already:
            print(f"  line {line}: {key!r} -> {target!r}")
    if result.refused:
        print(f"refused ({len(result.refused)}):")
        for line, a, b, why in result.refused:
            print(f"  line {line}: {a!r} / {b!r}: {why}")
    if result.added:
        print()
        print(diff(original, updated, aliases_path.name), end="")
    if not write:
        if result.added:
            print("\ndry run: nothing written. Add --write to write the file.")
        return result
    if result.added:
        aliases_path.write_text(updated, encoding="utf-8")
        print(f"\nwrote {aliases_path}. Next, one at a time:")
        for command in FOLLOW_UP:
            print(f"  {command}")
    else:
        print("nothing to write")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.cleaning.aliases",
        description="Promote approved match-review pairs into company_aliases.json.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    apply_p = sub.add_parser("apply", help="read a candidate CSV (dry run unless --write)")
    apply_p.add_argument("--from", dest="csv", type=Path, required=True, help="a candidate CSV")
    apply_p.add_argument("--write", action="store_true", help="write the alias file")
    apply_p.add_argument("--aliases", type=Path, default=ALIASES_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        apply(args.csv, args.aliases, write=args.write)
    except (CandidateFileError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
