"""The daily run scripts: both start the database container before Python.

run_daily.sh runs for real here, from a temp copy of the repo layout, with a
fake `docker` and a fake `.venv/bin/python` -- so no container is touched
and no pipeline runs. run_daily.ps1 can't run on this machine; it gets the
static checks (ASCII only, docker before Python).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "run_daily.sh"
PS1_FILES = sorted((ROOT / "scripts" / "windows").glob("*.ps1"))


def _exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def layout(tmp_path):
    """tmp/scripts/run_daily.sh + a fake venv python that records its args
    and exits 7, and a bin dir holding only `dirname` (and maybe docker)."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SH, tmp_path / "scripts" / "run_daily.sh")
    _exe(tmp_path / ".venv" / "bin" / "python", f'echo "$@" > "{tmp_path}/python.args"\nexit 7\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "dirname").symlink_to(shutil.which("dirname"))
    return tmp_path


def run_sh(layout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/sh", str(layout / "scripts" / "run_daily.sh"), *args],
        env={"PATH": str(layout / "bin"), "HOME": str(layout)},
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "docker_exit,said",
    [
        (0, "run_daily: ran 'docker compose up -d db'"),
        (1, "run_daily: 'docker compose up -d db' failed; the runner will wait for the database"),
    ],
)
def test_sh_starts_db_then_runs_the_pipeline(layout, docker_exit, said):
    _exe(layout / "bin" / "docker", f'echo "$@" > "{layout}/docker.args"\nexit {docker_exit}\n')
    done = run_sh(layout, "--db-wait", "0")
    assert done.returncode == 7  # the pipeline's own exit code, whatever docker did
    assert said in done.stdout
    assert (layout / "docker.args").read_text().split() == ["compose", "up", "-d", "db"]
    assert (layout / "python.args").read_text().split() == [
        "-m",
        "src.pipeline.daily",
        "--once-per-day",
        "--db-wait",
        "0",
    ]


def test_sh_without_docker_says_so_and_still_runs(layout):
    done = run_sh(layout)
    assert done.returncode == 7
    assert "docker not found on PATH" in done.stdout
    assert (layout / "python.args").exists()


@pytest.mark.parametrize("path", PS1_FILES, ids=lambda p: p.name)
def test_ps1_files_are_ascii_only(path):
    assert path.read_bytes().isascii(), f"{path.name}: Windows PowerShell 5.1 misreads UTF-8"


def test_ps1_starts_db_before_python_and_ignores_its_failure():
    text = (ROOT / "scripts" / "windows" / "run_daily.ps1").read_text()
    assert 'Get-Command "docker"' in text
    assert text.index("& docker compose up -d db") < text.index(
        "-m src.pipeline.daily --once-per-day @args"
    )
    # docker's exit code never becomes the script's: only the pipeline's is returned
    assert text.rstrip().endswith("exit $LASTEXITCODE")
    assert [ln.strip() for ln in text.splitlines() if ln.strip().startswith("exit")] == [
        "exit $LASTEXITCODE"
    ]


@pytest.mark.skipif(os.name != "posix", reason="POSIX sh only")
def test_sh_is_valid_posix_sh():
    assert subprocess.run(["/bin/sh", "-n", str(SH)]).returncode == 0


def test_both_run_scripts_pass_once_per_day_on_every_branch():
    ps1 = (ROOT / "scripts" / "windows" / "run_daily.ps1").read_text()
    sh = SH.read_text()
    calls = [ln for ln in ps1.splitlines() + sh.splitlines() if "-m src.pipeline.daily" in ln]
    calls = [ln for ln in calls if not ln.lstrip().startswith("#")]
    assert len(calls) == 4 and all("--once-per-day" in ln for ln in calls)
    assert '& "$venvPython" -m src.pipeline.daily' in ps1  # the path is quoted


def test_register_task_defaults_to_three_daily_triggers_with_unchanged_settings():
    text = (ROOT / "scripts" / "windows" / "register_daily_task.ps1").read_text()
    assert '[string[]]$Time = @("07:15", "13:15", "19:15")' in text
    # one trigger per time, all on the one task
    assert "$triggers += New-ScheduledTaskTrigger -Daily -At $at" in text
    assert "-Trigger $triggers" in text and text.count("Register-ScheduledTask") == 1
    assert '$_ -split ","' in text  # -File passes "07:15","13:15" as one string
    for setting in (
        "-StartWhenAvailable",
        "-RunOnlyIfNetworkAvailable",
        "-MultipleInstances IgnoreNew",
        "-ExecutionTimeLimit (New-TimeSpan -Hours 1)",
        "-LogonType Interactive",
        "-RunLevel Limited",
        '$TaskName = "JobMarketTracker-Daily"',
    ):
        assert setting in text, setting
    # the action still runs run_daily.ps1, with its path quoted
    assert '-File `"$runScript`"' in text
