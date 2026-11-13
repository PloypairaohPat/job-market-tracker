"""Which postings from the last few days fit my profile? A private shortlist.

Run:  python -m src.shortlist [--profile shortlist.toml] [--out data/shortlist]
      (or: make shortlist)

Reads a profile (copy shortlist.example.toml to shortlist.toml, which is
gitignored), selects analysis-population postings first seen within the
look-back window that pass every filter, collapses reposts into one entry
per (employer, normalized title), and writes

    <out>/shortlist-<UTC date>.md   and   <out>/shortlist-<UTC date>.csv

then prints the count and the path. The output names postings and
employers, like the private Visa outlook dashboard, so it is never
committed: the default <out> is data/shortlist/ (gitignored), and an
output directory inside the repo that git tracks or doesn't ignore is
refused. Nothing here calls an API; it reads DATABASE_URL only.

Filters (all optional; see shortlist.example.toml):
  lookback_days                 first_seen_at within the last N days (7)
  title_include / title_exclude case-insensitive substrings of the title
  skills_any / skills_all       job_skills at confidence >= 0.8
  metros, include_remote        tracked metros (src/cleaning/metro.py);
                                remote postings kept when include_remote
  seniority, include_no_seniority_signal
                                title-based levels; postings with no title
                                signal kept (and labelled) by default
  min_salary, min_salary_uses_predicted
                                applied to employer-disclosed salaries with
                                salary_quality 'ok' only; Adzuna's predicted
                                salaries are shown, labelled, and never
                                exclude unless the profile opts in
  visa_buckets                  v_job_visa_outlook buckets
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, make_url, text

from src.cleaning.metro import METRO_CITIES
from src.cleaning.skill_extractor import load_taxonomy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "shortlist.toml"
EXAMPLE_PROFILE = ROOT / "shortlist.example.toml"
DEFAULT_OUT = ROOT / "data" / "shortlist"

SKILL_CONFIDENCE = 0.8
SENIORITY_LEVELS = ("junior", "mid", "senior", "lead")
VISA_BUCKETS = ("strong", "possible", "unknown", "closed")
ANNUAL_FACTOR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}
NO_SIGNAL = "no title signal"
TRUNCATION_CAVEAT = (
    "Commercial (Adzuna) descriptions are truncated by the API, so a skill "
    "missing from a commercial posting may simply have been cut off; skill "
    "filters can drop commercial postings that do ask for the skill."
)


class ProfileError(ValueError):
    """The profile can't be used as written; the message says why."""


class UnsafeOutputError(RuntimeError):
    """The output directory could end up in git."""


@dataclass(frozen=True)
class Profile:
    lookback_days: int = 7
    title_include: tuple[str, ...] = ()
    title_exclude: tuple[str, ...] = ()
    skills_any: tuple[str, ...] = ()
    skills_all: tuple[str, ...] = ()
    metros: tuple[str, ...] = ()
    include_remote: bool = True
    seniority: tuple[str, ...] = ()
    include_no_seniority_signal: bool = True
    min_salary: int | None = None
    min_salary_uses_predicted: bool = False
    visa_buckets: tuple[str, ...] = ()


# --------------------------------------------------------------------- #
# the profile


def load_profile(path: Path, skill_names: Iterable[str] | None = None) -> Profile:
    """Read and validate a TOML profile. Unknown keys and values are errors,
    so a typo can't silently empty the shortlist."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path.name} isn't valid TOML: {exc}") from exc
    return parse_profile(raw, skill_names)


def parse_profile(raw: dict[str, Any], skill_names: Iterable[str] | None = None) -> Profile:
    known = {f.name: f for f in fields(Profile)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ProfileError(f"unknown option(s): {', '.join(unknown)} (see shortlist.example.toml)")
    values: dict[str, Any] = {}
    for name, value in raw.items():
        default = known[name].default
        if isinstance(default, tuple):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ProfileError(f"{name} must be a list of strings")
            values[name] = tuple(v.strip() for v in value if v.strip())
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ProfileError(f"{name} must be true or false")
            values[name] = value
        else:  # lookback_days, min_salary
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProfileError(f"{name} must be a whole number >= 0")
            values[name] = value
    profile = Profile(**values)
    if profile.lookback_days < 1:
        raise ProfileError("lookback_days must be at least 1")
    _check_choices("metros", profile.metros, METRO_CITIES)
    _check_choices("seniority", profile.seniority, SENIORITY_LEVELS)
    _check_choices("visa_buckets", profile.visa_buckets, VISA_BUCKETS)
    names = list(skill_names if skill_names is not None else (s.name for s in load_taxonomy()))
    canonical = {n.lower(): n for n in names}
    for option in ("skills_any", "skills_all"):
        chosen = getattr(profile, option)
        _check_choices(option, [c.lower() for c in chosen], canonical)
        profile = replace(profile, **{option: tuple(canonical[c.lower()] for c in chosen)})
    return profile


def _check_choices(name: str, chosen: Iterable[str], allowed: Iterable[str]) -> None:
    allowed = set(allowed)
    bad = [c for c in chosen if c not in allowed]
    if bad:
        shown = ", ".join(sorted(allowed)) if len(allowed) <= 12 else "the skill taxonomy names"
        raise ProfileError(f"{name}: {', '.join(bad)} not recognised (choose from {shown})")


# --------------------------------------------------------------------- #
# reading postings


CANDIDATES_SQL = """
SELECT
    j.id                AS job_id,
    j.source,
    j.title,
    COALESCE(NULLIF(j.title_normalized, ''), lower(trim(j.title))) AS title_key,
    c.normalized_name   AS employer_key,
    c.canonical_name    AS employer,
    l.city,
    l.state,
    l.metro_area,
    j.is_remote,
    j.seniority,
    j.salary_min,
    j.salary_max,
    j.salary_period,
    j.salary_currency,
    j.salary_is_predicted,
    j.salary_quality,
    j.redirect_url,
    j.first_seen_at,
    COALESCE(o.bucket, 'unknown') AS visa_bucket
FROM jobs j
LEFT JOIN companies c ON c.id = j.company_id
LEFT JOIN locations l ON l.id = j.location_id
LEFT JOIN v_job_visa_outlook o ON o.job_id = j.id
WHERE (j.source = 'adzuna' OR (j.source = 'usajobs' AND j.in_scope))
  AND j.first_seen_at >= :since
ORDER BY j.first_seen_at DESC, j.id DESC
"""

SKILLS_SQL = """
SELECT js.job_id, s.name
FROM job_skills js JOIN skills s ON s.id = js.skill_id
WHERE js.confidence >= :confidence AND js.job_id = ANY(:ids)
ORDER BY s.name
"""


def fetch_postings(conn, since: datetime) -> list[dict[str, Any]]:
    """Analysis-population postings first seen at or after `since`, with their
    matched skills (confidence >= SKILL_CONFIDENCE) under "skills"."""
    rows = [dict(r) for r in conn.execute(text(CANDIDATES_SQL), {"since": since}).mappings()]
    skills: dict[int, list[str]] = {}
    if rows:
        for job_id, name in conn.execute(
            text(SKILLS_SQL),
            {"confidence": SKILL_CONFIDENCE, "ids": [r["job_id"] for r in rows]},
        ):
            skills.setdefault(job_id, []).append(name)
    for r in rows:
        r["skills"] = skills.get(r["job_id"], [])
    return rows


# --------------------------------------------------------------------- #
# filtering (pure: tests feed invented dicts)


def annual_salary(row: dict[str, Any]) -> float | None:
    """Top of the range, annualized; None when there's nothing to compare."""
    top = row.get("salary_max") if row.get("salary_max") is not None else row.get("salary_min")
    factor = ANNUAL_FACTOR.get(row.get("salary_period") or "")
    if top is None or factor is None:
        return None
    return float(top) * factor


def keep(row: dict[str, Any], p: Profile) -> bool:
    title = (row.get("title") or "").lower()
    if p.title_include and not any(k.lower() in title for k in p.title_include):
        return False
    if any(k.lower() in title for k in p.title_exclude):
        return False
    skills = set(row.get("skills") or ())
    if p.skills_any and not skills & set(p.skills_any):
        return False
    if p.skills_all and not set(p.skills_all) <= skills:
        return False
    if p.metros:
        in_metro = row.get("metro_area") in p.metros
        if not (in_metro or (p.include_remote and row.get("is_remote"))):
            return False
    elif not p.include_remote and row.get("is_remote"):
        return False
    if p.seniority:
        level = row.get("seniority")
        if level is None:
            if not p.include_no_seniority_signal:
                return False
        elif level not in p.seniority:
            return False
    if p.min_salary is not None and row.get("salary_quality") == "ok":
        predicted = bool(row.get("salary_is_predicted"))
        if not predicted or p.min_salary_uses_predicted:
            annual = annual_salary(row)
            if annual is not None and annual < p.min_salary:
                return False
    if p.visa_buckets and row.get("visa_bucket") not in p.visa_buckets:
        return False
    return True


# --------------------------------------------------------------------- #
# collapsing reposts


@dataclass
class Entry:
    title: str
    employer: str
    locations: list[str]
    link: str
    salary: str
    salary_basis: str
    skills: list[str]
    visa_bucket: str
    seniority: str
    first_seen: str
    sources: list[str]
    postings: int
    job_ids: list[int] = field(default_factory=list)


def location_label(row: dict[str, Any]) -> str:
    place = ", ".join(x for x in (row.get("city"), row.get("state")) if x)
    if row.get("metro_area"):
        place = f"{place} ({row['metro_area']})" if place else row["metro_area"]
    if row.get("is_remote"):
        place = f"{place}, remote" if place else "remote"
    return place or "location not given"


def salary_text(row: dict[str, Any]) -> tuple[str, str]:
    """(the figure, its basis)."""
    lo, hi = row.get("salary_min"), row.get("salary_max")
    if lo is None and hi is None:
        return "", "not given"
    currency = row.get("salary_currency") or ""
    prefix = "$" if currency in ("USD", "") else f"{currency} "
    shown = [v for v in (lo, hi) if v is not None]
    if len(shown) == 2 and lo == hi:
        shown = [lo]
    money = "–".join(f"{prefix}{float(v):,.0f}" for v in shown)
    per = f" a {row['salary_period']}" if row.get("salary_period") else ""
    if row.get("salary_is_predicted"):
        basis = "Adzuna's estimate"
    else:
        basis = "employer-disclosed"
    if row.get("salary_quality") not in (None, "ok"):
        basis += f"; flagged {row['salary_quality']}"
    return f"{money}{per}", basis


def collapse(rows: list[dict[str, Any]]) -> list[Entry]:
    """One entry per (employer, normalized title), newest posting first.
    `rows` must be newest first (fetch_postings orders them that way)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        employer = row.get("employer_key") or row.get("employer") or "(no employer)"
        key = (employer, row.get("title_key") or (row.get("title") or "").strip().lower())
        groups.setdefault(key, []).append(row)
    entries = []
    for group in groups.values():
        newest = group[0]
        figure, basis = salary_text(newest)
        locations = list(dict.fromkeys(location_label(r) for r in group))
        skills = sorted({s for r in group for s in r.get("skills") or ()})
        buckets = list(dict.fromkeys(r.get("visa_bucket") or "unknown" for r in group))
        entries.append(
            Entry(
                title=newest.get("title") or "",
                employer=newest.get("employer") or "(no employer)",
                locations=locations,
                link=newest.get("redirect_url") or "",
                salary=figure,
                salary_basis=basis,
                skills=skills,
                visa_bucket=" / ".join(buckets),
                seniority=newest.get("seniority") or NO_SIGNAL,
                first_seen=_date(newest.get("first_seen_at")),
                sources=sorted({r.get("source") or "" for r in group}),
                postings=len(group),
                job_ids=[r["job_id"] for r in group],
            )
        )
    return entries


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    return str(value or "")


# --------------------------------------------------------------------- #
# output


def render_markdown(
    entries: list[Entry], profile: Profile, generated: datetime, database: str, synthetic: bool
) -> str:
    lines = [
        f"# Shortlist, {generated:%Y-%m-%d}",
        "",
        "Private: this file names postings and employers. Never commit it.",
        "",
    ]
    if synthetic:
        lines += ["**Synthetic demo data, not real postings.**", ""]
    lines += [
        f"Generated {generated:%Y-%m-%d %H:%M} UTC from `{database}`: postings first seen in "
        f"the last {profile.lookback_days} day(s) that pass the profile, reposts collapsed "
        "into one entry per employer and title, newest first.",
        "",
    ]
    if any("adzuna" in e.sources for e in entries):
        lines += [f"> {TRUNCATION_CAVEAT}", ""]
    lines += [f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}.", ""]
    for e in entries:
        lines.append(f"## {e.title}, {e.employer}")
        lines.append("")
        lines.append(f"- Where: {'; '.join(e.locations)}")
        lines.append(f"- Link: {e.link or 'none stored'}")
        salary = f"{e.salary} ({e.salary_basis})" if e.salary else "not given"
        lines.append(f"- Salary: {salary}")
        lines.append(f"- Skills matched: {', '.join(e.skills) or 'none at confidence >= 0.8'}")
        lines.append(f"- Visa outlook: {e.visa_bucket}")
        lines.append(f"- Seniority: {e.seniority}")
        lines.append(
            f"- First seen {e.first_seen} on {', '.join(e.sources)}; "
            f"{e.postings} posting{'s' if e.postings != 1 else ''}"
        )
        lines.append("")
    return "\n".join(lines)


CSV_COLUMNS = (
    "title",
    "employer",
    "locations",
    "link",
    "salary",
    "salary_basis",
    "skills",
    "visa_bucket",
    "seniority",
    "first_seen",
    "sources",
    "postings",
)


def write_csv(entries: list[Entry], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for e in entries:
            writer.writerow(
                [
                    e.title,
                    e.employer,
                    "; ".join(e.locations),
                    e.link,
                    e.salary,
                    e.salary_basis,
                    ", ".join(e.skills),
                    e.visa_bucket,
                    e.seniority,
                    e.first_seen,
                    ", ".join(e.sources),
                    e.postings,
                ]
            )


GitRunner = Callable[[list[str], Path], tuple[int, str]]


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 128, ""
    return done.returncode, done.stdout


def check_output_dir(out: Path, root: Path = ROOT, git: GitRunner = _git) -> None:
    """Refuse a directory inside the repo that git tracks or doesn't ignore."""
    out = out.resolve()
    root = root.resolve()
    if out != root and root not in out.parents:
        return  # outside the repo: git can't commit it
    rel = out.relative_to(root).as_posix() or "."
    code, tracked = git(["ls-files", "--", rel], root)
    if code != 0:
        raise UnsafeOutputError(
            f"can't ask git whether {rel} is tracked; use the default data/shortlist/"
        )
    if tracked.strip():
        raise UnsafeOutputError(f"{rel} holds files git tracks; the shortlist is private")
    code, _ = git(["check-ignore", "-q", "--", f"{rel}/shortlist-probe.md"], root)
    if code != 0:
        raise UnsafeOutputError(
            f"{rel} isn't gitignored, so the shortlist could be committed; "
            "use the default data/shortlist/"
        )


def run(
    database_url: str,
    profile: Profile,
    out: Path,
    now: datetime | None = None,
    root: Path = ROOT,
    git: GitRunner = _git,
) -> tuple[list[Entry], Path]:
    check_output_dir(out, root, git)
    now = now or datetime.now(UTC)
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            rows = fetch_postings(conn, now - timedelta(days=profile.lookback_days))
    finally:
        engine.dispose()
    entries = collapse([r for r in rows if keep(r, profile)])
    url = make_url(database_url)
    name = url.database or ""
    synthetic = "demo" in name or "test" in name
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"shortlist-{now:%Y-%m-%d}.md"
    md.write_text(
        render_markdown(entries, profile, now, f"{url.host}/{name}", synthetic),
        encoding="utf-8",
    )
    write_csv(entries, md.with_suffix(".csv"))
    return entries, md


def main(argv: list[str] | None = None) -> int:
    argp = argparse.ArgumentParser(description="A private shortlist of recent postings.")
    argp.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    argp.add_argument("--out", type=Path, default=DEFAULT_OUT)
    argp.add_argument("--database-url", default=None, help="default: DATABASE_URL")
    args = argp.parse_args(argv)

    if not args.profile.exists():
        print(
            f"No profile at {args.profile}. Create one from the example, then edit it:\n"
            '  Copy-Item "shortlist.example.toml" "shortlist.toml"\n'
            '  notepad "shortlist.toml"\n'
            '(POSIX: cp "shortlist.example.toml" "shortlist.toml")',
            file=sys.stderr,
        )
        return 2
    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"Profile problem in {args.profile.name}: {exc}", file=sys.stderr)
        return 2
    database_url = args.database_url
    if not database_url:
        from src.utils.config import get_settings

        database_url = get_settings().database_url
    try:
        entries, path = run(database_url, profile, args.out)
    except UnsafeOutputError as exc:
        print(f"Refusing to write the shortlist: {exc}", file=sys.stderr)
        return 2
    print(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} -> {path}")
    print(f"CSV: {path.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
