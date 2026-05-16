import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_RCFILE = PROJECT_ROOT / "pyproject.toml"
COVERAGE_DIR = PROJECT_ROOT / ".coverage_data"
PTH_FILENAME = "lac-coverage-subprocess.pth"


def pytest_configure(config: pytest.Config) -> None:
    """Install the subprocess coverage hook in the active venv.

    `coverage.process_startup()` is a no-op unless COVERAGE_PROCESS_START is
    set, so leaving the .pth installed outside test runs is harmless.
    """
    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    site_packages = Path(sysconfig.get_paths()["purelib"])
    pth = site_packages / PTH_FILENAME
    if not pth.exists():
        pth.write_text("import coverage; coverage.process_startup()\n")


@pytest.fixture(autouse=True)
def _subprocess_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject coverage hooks into every subprocess started during a test.

    Children write parallel coverage fragments into ``.coverage_data/`` so the
    project root stays clean. The session-end fixture combines them.
    """
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(COVERAGE_RCFILE))
    monkeypatch.setenv("COVERAGE_FILE", str(COVERAGE_DIR / "cov"))


@pytest.fixture(scope="session", autouse=True)
def _combine_coverage_on_exit() -> Callable[[], None]:
    """Combine parallel coverage fragments at session end.

    pytest-cov usually does this, but it can be skipped on interrupted runs.
    Running ``coverage combine`` again is a no-op when fragments are absent.
    """
    yield
    subprocess.run(
        [sys.executable, "-m", "coverage", "combine"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )


@pytest.fixture
def lac_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated LAC_HOME under tmp_path. Disables color + interactivity."""
    home = tmp_path / "lh"
    monkeypatch.setenv("LAC_HOME", str(home))
    monkeypatch.setenv("LAC_NONINTERACTIVE", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    return home


@pytest.fixture
def make_git_repo(tmp_path: Path) -> Callable[..., Path]:
    """Factory that creates fresh git repos in tmp_path."""
    counter = {"n": 0}

    def _make(name: str | None = None) -> Path:
        repo_name = name or f"repo{counter['n']}"
        counter["n"] += 1
        repo = tmp_path / repo_name
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        return repo

    return _make


@pytest.fixture
def run_lac(lac_home: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run `python -m lac <args>` with isolated LAC_HOME.

    The `lac_home` fixture sets env vars via monkeypatch; subprocess inherits them.
    """

    def _run(
        *args: str,
        cwd: Path,
        check: bool = True,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cp = subprocess.run(
            [sys.executable, "-m", "lac", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            input=stdin,
        )
        if check and cp.returncode != 0:
            raise AssertionError(
                f"lac {' '.join(args)} failed (rc={cp.returncode})\n"
                f"--- stdout ---\n{cp.stdout}\n--- stderr ---\n{cp.stderr}"
            )
        return cp

    return _run
