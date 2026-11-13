"""The provenance stamp at the top of every rendered report.

Database name (from the database itself, `current_database()`), generation
time (UTC), git commit, and the row count of every view the report read. A
database whose name contains "demo" or "test" also gets DEMO_BANNER, so a
report rendered on synthetic data can't be mistaken for findings.

The commit comes from REPORT_GIT_COMMIT when set (the pipeline image has no
.git, so `make prod-report` passes the host checkout's commit), else from
`git rev-parse`, marked "-dirty" when tracked files have uncommitted changes.
`--publish` leaves out the files publishing itself writes (docs/reports/ and
README.md): the narrative is in the published file, and a second publish
after fixing it would otherwise stamp the unchanged code "-dirty".
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_BANNER = "Synthetic demo data, not market findings."
COMMIT_ENV = "REPORT_GIT_COMMIT"


def is_demo_database(name: str) -> bool:
    lowered = name.lower()
    return "demo" in lowered or "test" in lowered


def git_commit(repo_root: Path = REPO_ROOT, ignore: tuple[str, ...] = ()) -> str:
    """The checkout's short commit, "-dirty" when a tracked file outside the
    `ignore` paths (relative to the repo root) has uncommitted changes."""
    if os.environ.get(COMMIT_ENV):
        return os.environ[COMMIT_ENV]

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        commit = git("rev-parse", "--short=12", "HEAD")
        excludes = [f":(exclude){path}" for path in ignore]
        dirty = git("status", "--porcelain", "--untracked-files=no", "--", ".", *excludes)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{commit}-dirty" if dirty else commit


@dataclass(frozen=True)
class Provenance:
    database: str
    generated_at: datetime
    git_commit: str
    view_rows: dict[str, int] = field(default_factory=dict)

    @property
    def is_demo(self) -> bool:
        return is_demo_database(self.database)

    @classmethod
    def collect(
        cls, database: str, view_rows: dict[str, int], ignore_dirty: tuple[str, ...] = ()
    ) -> Provenance:
        return cls(
            database=database,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            git_commit=git_commit(ignore=ignore_dirty),
            view_rows=dict(sorted(view_rows.items())),
        )
