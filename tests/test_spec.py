"""Specification tests — one assertion per locked-in decision.

Each test maps to a row in CLAUDE.md's locked-decision table. When a decision
changes, the corresponding test changes; when a test fails, either the
implementation drifted or the decision needs an explicit update in CLAUDE.md.

Distinct from `test_e2e.py`, which exercises happy-path workflows end-to-end.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

AGENT_CONFIG_FILES = ["CLAUDE.md", "AGENTS.md", ".claude", ".agents", ".cursorrules", ".mcp.json"]
SLUG_PATTERN = re.compile(r"^[^/]+-[0-9a-f]{6}$")


def test_lac_home_prefers_lac_home_env_over_xdg(tmp_path, monkeypatch, make_git_repo):
    lac_home = tmp_path / "lh"
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("LAC_HOME", str(lac_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("NO_COLOR", "1")

    repo = make_git_repo()
    cp = subprocess.run(
        [sys.executable, "-m", "lac", "home"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert cp.stdout.strip() == str(lac_home)


def test_lac_home_falls_back_to_xdg_data_home(tmp_path, monkeypatch, make_git_repo):
    xdg = tmp_path / "xdg"
    monkeypatch.delenv("LAC_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("NO_COLOR", "1")

    repo = make_git_repo()
    cp = subprocess.run(
        [sys.executable, "-m", "lac", "home"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert cp.stdout.strip() == str(xdg / "lac")


def test_lac_home_defaults_to_local_share_when_neither_set(tmp_path, monkeypatch, make_git_repo):
    monkeypatch.delenv("LAC_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NO_COLOR", "1")

    repo = make_git_repo()
    cp = subprocess.run(
        [sys.executable, "-m", "lac", "home"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert cp.stdout.strip() == str(tmp_path / ".local/share/lac")


def _active_slug_dirs(lac_home: Path) -> list[Path]:
    return [
        p
        for p in lac_home.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and not p.name.startswith("_")
        and ".bak." not in p.name
    ]


def test_slug_name_matches_decision_format(make_git_repo, run_lac, lac_home):
    repo = make_git_repo("myproject")
    run_lac("register", cwd=repo)
    slug_dirs = _active_slug_dirs(lac_home)
    assert len(slug_dirs) == 1
    slug = slug_dirs[0].name
    assert SLUG_PATTERN.match(slug), f"slug {slug!r} does not match {{name}}-{{6hex}}"
    assert slug.startswith("myproject-")


def test_slug_hash_is_deterministic_for_same_path(make_git_repo, run_lac, lac_home):
    repo = make_git_repo("samename")
    run_lac("register", cwd=repo)
    slug1 = _active_slug_dirs(lac_home)[0].name

    run_lac("unregister", "--yes", cwd=repo)
    run_lac("register", cwd=repo)
    slug2 = _active_slug_dirs(lac_home)[0].name
    assert slug1 == slug2


def test_slug_hash_differs_for_different_paths(make_git_repo, run_lac, lac_home):
    repo_a = make_git_repo("a")
    repo_b = make_git_repo("b")
    run_lac("register", cwd=repo_a)
    run_lac("register", cwd=repo_b)
    slugs = sorted(p.name for p in _active_slug_dirs(lac_home))
    assert len(slugs) == 2
    hash_a = slugs[0].rsplit("-", 1)[1]
    hash_b = slugs[1].rsplit("-", 1)[1]
    assert hash_a != hash_b


def test_register_auto_skips_untracked_when_noninteractive(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")  # untracked
    cp = run_lac("register", cwd=repo)
    # The untracked file should NOT be replaced by a symlink.
    assert (repo / "CLAUDE.md").is_file()
    assert not (repo / "CLAUDE.md").is_symlink()
    assert "skip" in cp.stdout.lower()


def test_register_skip_on_stdin_s(make_git_repo, run_lac, lac_home, monkeypatch):
    monkeypatch.delenv("LAC_NONINTERACTIVE", raising=False)
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")
    run_lac("register", cwd=repo, stdin="s\n")
    assert (repo / "CLAUDE.md").is_file()
    assert not (repo / "CLAUDE.md").is_symlink()


def test_register_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("register", cwd=non_git, check=False)
    assert cp.returncode == 1


def test_link_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("link", "FOO.md", cwd=non_git, check=False)
    assert cp.returncode == 1


def test_unregister_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("unregister", "--yes", cwd=non_git, check=False)
    assert cp.returncode == 1


def test_status_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("status", cwd=non_git, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not a git repository" in output


def test_path_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("path", cwd=non_git, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not a git repository" in output


@pytest.mark.parametrize(
    "cmd_args",
    [
        ["link", "FILE.md"],
        ["unregister", "--yes"],
        ["status"],
        ["path"],
    ],
)
def test_command_in_unregistered_repo_errors_not_registered(cmd_args, make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac(*cmd_args, cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not registered" in output
    assert "lac register" in output


def test_link_before_register_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("link", "CUSTOM.md", cwd=repo, check=False)
    assert cp.returncode == 1


@pytest.mark.parametrize("bad_arg", ["/abs/path.md", "../escape.md", ""])
def test_link_invalid_arg_exits_one(bad_arg, make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("link", bad_arg, cwd=repo, check=False)
    assert cp.returncode == 1


def test_path_in_unregistered_repo_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("path", cwd=repo, check=False)
    assert cp.returncode == 1


def test_path_rejects_invalid_file_arg(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("path", "/abs/path.md", cwd=repo, check=False)
    assert cp.returncode == 1


def test_unregister_creates_timestamped_backup(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("unregister", "--yes", cwd=repo)
    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    assert len(backups) == 1
    # Pattern: <slug>.bak.YYMMDD-HHMMSS
    assert re.match(r".*\.bak\.\d{6}-\d{6}$", backups[0].name)


def test_register_creates_slug_and_meta_only(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    slug_entries = {p.name for p in slug.iterdir()}
    assert slug_entries == {".lac.meta", ".lac.local"}
    for name in AGENT_CONFIG_FILES:
        assert not (repo / name).exists(), f"{name} must not exist after register-only"


def test_register_prints_lac_link_hint(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    cp = run_lac("register", cwd=repo)
    assert "lac link" in cp.stdout


def test_link_skips_tracked_file_with_message(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("tracked content\n")
    subprocess.run(["git", "add", "CLAUDE.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )

    run_lac("register", cwd=repo)
    cp = run_lac("link", "CLAUDE.md", cwd=repo)
    assert (repo / "CLAUDE.md").is_file()
    assert not (repo / "CLAUDE.md").is_symlink()
    assert "tracked" in cp.stdout.lower()


def test_link_places_symlink_into_lac_home_slug(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    for name in AGENT_CONFIG_FILES:
        run_lac("link", name, cwd=repo)
        link = repo / name
        assert link.is_symlink()
        resolved = link.resolve()
        assert str(resolved).startswith(str(lac_home)), (
            f"{name} resolves to {resolved}, expected under {lac_home}"
        )


def test_link_records_linked_files_in_meta(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    for name in AGENT_CONFIG_FILES:
        run_lac("link", name, cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta_text = (slug / ".lac.meta").read_text()
    for name in AGENT_CONFIG_FILES:
        assert name in meta_text


def test_template_dir_is_created_in_lac_home(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    template = lac_home / "_template"
    assert template.is_dir()
    for name in AGENT_CONFIG_FILES:
        assert (template / name).exists(), f"_template/{name} missing"


@pytest.mark.parametrize(
    "raw_url",
    [
        "git@github.com:user/repo.git",
        "https://github.com/user/repo.git",
        "https://github.com/user/repo",
        "git://github.com/user/repo.git",
        "https://GitHub.com/USER/repo.git",
    ],
)
def test_remote_url_normalizes_to_same_identifier(raw_url):
    from lac.gitutil import _normalize_remote_url

    assert _normalize_remote_url(raw_url) == "github.com/user/repo"


def test_register_does_not_create_entries_in_repo(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    repo_entries = {p.name for p in repo.iterdir() if not p.name.startswith(".git")}
    assert repo_entries == set(), f"register must not create files in repo, found: {repo_entries}"


def test_ensure_lac_home_exits_one_when_path_is_a_file(lac_home, run_lac, tmp_path):
    lac_home.write_text("not a directory\n")
    cp = run_lac("home", cwd=tmp_path, check=False)
    assert cp.returncode == 1
    assert "lac home path is a file" in cp.stderr


def test_lac_link_all_links_every_standard_file(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    for name in AGENT_CONFIG_FILES:
        assert (repo / name).is_symlink(), f"{name} not linked after lac link --all"


def test_lac_link_all_includes_custom_from_meta(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "CUSTOM.md", cwd=repo)
    (repo / "CUSTOM.md").unlink()
    run_lac("link", "--all", cwd=repo)
    assert (repo / "CUSTOM.md").is_symlink()
    slug = _active_slug_dirs(lac_home)[0]
    meta_text = (slug / ".lac.meta").read_text()
    assert "CUSTOM.md" in meta_text


def test_lac_link_all_idempotent_when_everything_already_linked(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    exclude_before = (repo / ".git/info/exclude").read_text()
    run_lac("link", "--all", cwd=repo)
    exclude_after = (repo / ".git/info/exclude").read_text()
    assert exclude_before == exclude_after
    for name in AGENT_CONFIG_FILES:
        assert (repo / name).is_symlink()


def test_lac_link_all_auto_skips_untracked_conflict_in_non_interactive(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    assert (repo / "CLAUDE.md").read_text() == "user content\n"
    assert not (repo / "CLAUDE.md").is_symlink()
    slug = _active_slug_dirs(lac_home)[0]
    assert not (slug / "CLAUDE.md").exists() or (slug / "CLAUDE.md").read_text() != "user content\n"


def test_lac_link_all_links_unaffected_entries_when_one_conflicts(make_git_repo, run_lac):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    assert not (repo / "CLAUDE.md").is_symlink()
    for name in AGENT_CONFIG_FILES:
        if name == "CLAUDE.md":
            continue

        assert (repo / name).is_symlink(), f"{name} not linked despite conflict on CLAUDE.md"


def test_lac_link_no_args_exits_one_in_non_interactive_mode(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("link", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "non-interactive" in output
    assert "--all" in output


def test_lac_link_all_with_file_argument_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("link", "--all", "CUSTOM.md", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "mutually exclusive" in output or "--all" in output


def test_lac_link_no_args_in_unregistered_repo_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("link", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not registered" in output
    assert "lac register" in output


def test_lac_link_all_in_unregistered_repo_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("link", "--all", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not registered" in output
    assert "lac register" in output


# --- POLICY_lac_home.md §1 — Ignore 정책 ---

# Hardcoded mirror of POLICY_lac_home.md §1. Do NOT import from gitutil — that would make
# the assertion a tautology. Edit this list only when POLICY §1 changes.
EXPECTED_LAC_HOME_IGNORE_PATTERNS = [
    "*.bak.*",
    ".DS_Store",
    ".idea/",
    ".vscode/",
    "*.swp",
    ".lac.local",
]


def _read_gitignore(home: Path) -> str:
    return (home / ".gitignore").read_text()


def test_lac_home_gitignore_contains_managed_patterns_in_marker_block(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    content = _read_gitignore(lac_home)
    assert "# === lac:start ===" in content
    assert "# === lac:end ===" in content
    start = content.index("# === lac:start ===")
    end = content.index("# === lac:end ===")
    block_lines = content[start:end].splitlines()
    for pattern in EXPECTED_LAC_HOME_IGNORE_PATTERNS:
        assert pattern in block_lines, f"{pattern!r} missing from lac block"


def test_lac_home_gitignore_preserves_user_lines_outside_marker_block(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    gitignore = lac_home / ".gitignore"
    original = gitignore.read_text()
    gitignore.write_text("user_top_line\n\n" + original + "user_bottom_line\n")
    run_lac("register", cwd=repo)
    after = gitignore.read_text()
    assert "user_top_line" in after
    assert "user_bottom_line" in after
    assert "# === lac:start ===" in after
    assert "# === lac:end ===" in after


def test_lac_home_gitignore_idempotent_on_repeated_init(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    first = _read_gitignore(lac_home)
    run_lac("register", cwd=repo)
    second = _read_gitignore(lac_home)
    assert first == second


# --- POLICY_lac_home.md §2 — Init 정책 ---


def test_lac_home_first_init_creates_main_branch(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    branch = subprocess.run(
        ["git", "-C", str(lac_home), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main", f"expected 'main', got {branch!r}"


def test_lac_home_first_init_prints_clone_hint(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    first = run_lac("register", cwd=repo)
    assert "lac home initialized at" in first.stderr
    assert "git clone" in first.stderr


def test_lac_home_second_init_does_not_reprint_hint(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    second = run_lac("register", cwd=repo)
    assert "lac home initialized at" not in second.stderr


# --- POLICY_lac_home.md §3 — 상태 가시화 ---


def _commit_all_in_lac_home(home: Path) -> None:
    subprocess.run(["git", "-C", str(home), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(home),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def test_status_prints_lac_home_git_clean_when_no_changes(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    _commit_all_in_lac_home(lac_home)
    cp = run_lac("status", cwd=repo)
    assert "lac_home_git" in cp.stdout
    assert "· clean" in cp.stdout


def test_status_prints_uncommitted_count_when_dirty(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    _commit_all_in_lac_home(lac_home)
    (lac_home / "dirty_marker.txt").write_text("noise\n")
    cp = run_lac("status", cwd=repo)
    assert "lac_home_git" in cp.stdout
    assert "1 uncommitted" in cp.stdout


def test_status_prints_merging_when_merge_head_exists(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    (lac_home / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
    cp = run_lac("status", cwd=repo)
    assert "lac_home_git" in cp.stdout
    assert "⚠ MERGING" in cp.stdout


def _git(git_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(git_dir), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _make_merge_conflict(git_dir: Path, filename: str = "conflict.txt") -> None:
    """Leave `git_dir` mid-merge with `filename` as a `UU` conflict."""
    f = git_dir / filename
    f.write_text("base\n")
    _git(git_dir, "add", ".")
    _git(git_dir, "commit", "-q", "-m", "base")
    _git(git_dir, "checkout", "-q", "-b", "other")
    f.write_text("other side\n")
    _git(git_dir, "commit", "-q", "-am", "other")
    _git(git_dir, "checkout", "-q", "main")
    f.write_text("my side\n")
    _git(git_dir, "commit", "-q", "-am", "mine")
    # merge conflicts → nonzero exit; that's the point, so don't check.
    subprocess.run(
        ["git", "-C", str(git_dir), "-c", "user.email=t@t", "-c", "user.name=t", "merge", "other"],
        capture_output=True,
    )


def test_lac_home_git_status_lists_conflict_paths(tmp_path):
    from lac.gitutil import lac_home_git_status

    home = tmp_path / "h"
    home.mkdir()
    _git(home, "init", "-q", "-b", "main")
    _make_merge_conflict(home, "conflict.txt")
    st = lac_home_git_status(home)
    assert st is not None
    assert st.merging is True
    assert "conflict.txt" in st.conflict_paths


def test_status_prints_conflict_paths_when_lac_home_conflicted(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)  # creates lac_home git (main, uncommitted slug)
    _make_merge_conflict(lac_home, "conflict.txt")
    cp = run_lac("status", cwd=repo)
    assert "⚠ MERGING" in cp.stdout
    assert "conflict.txt" in cp.stdout


# --- SCENARIOS.md R-04 / R-05 — init_slug_dir repo_path 갱신 ---


def _add_remote(repo: Path, url: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", url],
        check=True,
        capture_output=True,
    )


def test_register_reuses_slug_for_same_remote_url(make_git_repo, run_lac, lac_home):
    repo_a = make_git_repo("orig")
    _add_remote(repo_a, "https://github.com/me/r.git")
    run_lac("register", cwd=repo_a)
    repo_b = make_git_repo("moved")
    _add_remote(repo_b, "https://github.com/me/r.git")
    run_lac("register", cwd=repo_b)
    assert len(_active_slug_dirs(lac_home)) == 1


def test_register_updates_lac_local_when_remote_matches_different_path(
    make_git_repo, run_lac, lac_home
):
    from lac.slugdir import read_local_path

    repo_a = make_git_repo("orig")
    _add_remote(repo_a, "https://github.com/me/r.git")
    run_lac("register", cwd=repo_a)
    repo_b = make_git_repo("moved")
    _add_remote(repo_b, "https://github.com/me/r.git")
    run_lac("register", cwd=repo_b)
    slug = _active_slug_dirs(lac_home)[0]
    assert read_local_path(slug) == repo_b.resolve()


def test_register_idempotent_when_repo_path_unchanged(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta_path = slug / ".lac.meta"
    before = meta_path.read_text()
    run_lac("register", cwd=repo)
    after = meta_path.read_text()
    assert before == after


# --- SCENARIOS.md U-03 — unregister backup ts collision ---


def test_unregister_avoids_backup_collision_on_same_second(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("unregister", "--yes", cwd=repo)
    run_lac("register", cwd=repo)
    run_lac("unregister", "--yes", cwd=repo)
    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    names = {p.name for p in backups}
    assert len(names) == 2, f"expected 2 distinct backup names, got {names}"


def test_unregister_appends_suffix_when_backup_name_taken(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    # Pre-create backup dirs for the next 3 seconds so unregister cannot use base ts.
    from datetime import datetime, timedelta

    now = datetime.now()
    for offset in range(3):
        ts = (now + timedelta(seconds=offset)).strftime("%y%m%d-%H%M%S")
        (lac_home / f"{slug.name}.bak.{ts}").mkdir(exist_ok=True)
    run_lac("unregister", "--yes", cwd=repo)
    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    suffixed = [p for p in backups if "-2" in p.name.rsplit(".bak.", 1)[1]]
    assert suffixed, f"expected a backup with -2 suffix, got {[p.name for p in backups]}"


# --- SCENARIOS.md U-07 — unregister unlinked 파일 안내 ---


def test_unregister_summary_lists_unlinked_files_preserved_in_backup(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta_path = slug / ".lac.meta"
    meta = yaml.safe_load(meta_path.read_text())
    meta["unlinked_files"] = ["old_notes.md"]
    meta_path.write_text(yaml.safe_dump(meta))
    (slug / "old_notes.md").write_text("user note\n")
    cp = run_lac("unregister", "--yes", cwd=repo)
    assert "unlinked preserved in backup" in cp.stdout
    assert "old_notes.md" in cp.stdout
    backup = next(p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name)
    assert (backup / "old_notes.md").read_text() == "user note\n"


def test_unregister_summary_omits_unlinked_line_when_none(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("unregister", "--yes", cwd=repo)
    assert "unlinked preserved" not in cp.stdout


# --- 정합성 진단 (exclude drift / gitignore 자동 복구) ---


def test_doctor_detects_exclude_drift_when_user_removes_lac_block_line(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    exclude = repo / ".git" / "info" / "exclude"
    # User edits: remove all lac-managed lines from the lac block.
    text = exclude.read_text()
    start_marker = "# === lac:start ==="
    end_marker = "# === lac:end ==="
    before = text.split(start_marker)[0]
    after = text.split(end_marker)[1]
    exclude.write_text(before + start_marker + "\n" + end_marker + after)
    cp = run_lac("doctor", cwd=repo)
    assert "exclude-drift" in cp.stdout


def test_lac_home_gitignore_block_is_overwritten_on_every_lac_call(
    make_git_repo, run_lac, lac_home
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    gitignore = lac_home / ".gitignore"
    text = gitignore.read_text()
    gitignore.write_text(text.replace("*.bak.*", "*.bak.tampered"))
    assert "*.bak.tampered" in gitignore.read_text()
    run_lac("status", cwd=repo)
    after = gitignore.read_text()
    assert "*.bak.*" in after
    assert "*.bak.tampered" not in after


def test_doctor_passes_when_exclude_and_gitignore_blocks_intact(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "--all", cwd=repo)
    cp = run_lac("doctor", cwd=repo)
    assert "exclude-drift" not in cp.stdout
    assert "gitignore" not in (cp.stdout + cp.stderr).lower()


# --- .git/lac 슬러그 포인터 — cross-machine 입양 (no-remote repo) ---


def _seed_orphan_slug(lac_home: Path, name: str, remote: str | None = None) -> Path:
    """Create a slug present in lac home but not bound on this machine.

    No `.lac.local` is written, so the slug reads as registered on another
    machine (an adoption candidate / not-on-this-machine).
    """
    from lac.meta import Meta

    lac_home.mkdir(parents=True, exist_ok=True)
    slug = lac_home / name
    slug.mkdir()
    Meta(repo_remote=remote, created_at="x").save(slug / ".lac.meta")
    return slug


def test_register_writes_git_lac_pointer(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    assert (repo / ".git" / "lac").read_text().strip() == slug.name


def test_get_slug_dir_prefers_git_lac_pointer(make_git_repo, lac_home):
    from lac.gitutil import write_slug_pointer
    from lac.slugdir import get_slug_dir

    slug = _seed_orphan_slug(lac_home, "bound-aaa111")
    repo = make_git_repo("proj")  # no remote, different path
    write_slug_pointer(repo, "bound-aaa111")
    assert get_slug_dir(repo) == slug


def test_register_reuses_slug_after_repo_move_via_pointer(
    make_git_repo, run_lac, lac_home, tmp_path
):
    repo = make_git_repo("proj")
    run_lac("register", cwd=repo)
    assert len(_active_slug_dirs(lac_home)) == 1
    moved = tmp_path / "moved-proj"
    shutil.move(str(repo), str(moved))
    run_lac("register", cwd=moved)
    assert len(_active_slug_dirs(lac_home)) == 1  # pointer matched, no new slug


def test_register_creates_new_when_noninteractive_despite_orphan(make_git_repo, run_lac, lac_home):
    _seed_orphan_slug(lac_home, "other-deadbe")
    repo = make_git_repo("proj")
    run_lac("register", cwd=repo)  # LAC_NONINTERACTIVE=1 → no adopt prompt
    assert len(_active_slug_dirs(lac_home)) == 2


def test_adoptable_slugs_lists_only_orphans(make_git_repo, run_lac, lac_home):
    from lac.cli import _adoptable_slugs

    local = make_git_repo("localproj")
    run_lac("register", cwd=local)  # bound here (.lac.local) → not adoptable
    _seed_orphan_slug(lac_home, "remoteproj-bbb222")
    cwd = make_git_repo("remoteproj")
    names = [entry.name for entry, _ in _adoptable_slugs(lac_home, cwd)]
    assert "remoteproj-bbb222" in names
    assert all(not n.startswith("localproj") for n in names)


def test_adopt_slug_binds_pointer_and_writes_lac_local(make_git_repo, lac_home):
    from lac.cli import _adopt_slug
    from lac.gitutil import read_slug_pointer
    from lac.slugdir import read_local_path

    slug = _seed_orphan_slug(lac_home, "adopted-ccc333")
    repo = make_git_repo("proj")
    _adopt_slug(slug, repo)
    assert read_slug_pointer(repo) == "adopted-ccc333"
    assert read_local_path(slug) == repo.resolve()


# --- .lac.local 분리: synced meta에 머신 경로 없음 (충돌 제거) ---


def test_meta_has_no_repo_path_after_register(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta = yaml.safe_load((slug / ".lac.meta").read_text())
    assert "repo_path" not in meta


def test_register_writes_lac_local_with_repo_path(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    assert (slug / ".lac.local").read_text().strip() == str(repo.resolve())


def test_meta_load_ignores_legacy_repo_path_key(make_git_repo, run_lac, lac_home):
    from lac.meta import Meta

    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta_path = slug / ".lac.meta"
    data = yaml.safe_load(meta_path.read_text())
    data["repo_path"] = "/legacy/machine/path"  # simulate pre-migration file
    meta_path.write_text(yaml.safe_dump(data))
    assert Meta.load_safe(meta_path) is not None  # unknown key ignored, not corrupted


def test_register_strips_legacy_repo_path_from_meta(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    meta_path = slug / ".lac.meta"
    data = yaml.safe_load(meta_path.read_text())
    data["repo_path"] = "/legacy/machine/path"
    meta_path.write_text(yaml.safe_dump(data))
    run_lac("register", cwd=repo)  # re-save strips the legacy key
    assert "repo_path" not in yaml.safe_load(meta_path.read_text())


def test_list_marks_not_on_this_machine_when_local_absent(make_git_repo, run_lac, lac_home):
    _seed_orphan_slug(lac_home, "elsewhere-eee555")  # no .lac.local
    repo = make_git_repo()  # a cwd to run from
    cp = run_lac("list", cwd=repo)
    assert "not-on-this-machine" in cp.stdout


def test_doctor_classifies_not_on_this_machine_not_orphan(make_git_repo, run_lac, lac_home):
    _seed_orphan_slug(lac_home, "elsewhere-fff666")  # no .lac.local
    repo = make_git_repo()
    cp = run_lac("doctor", cwd=repo)
    assert "not-on-this-machine" in cp.stdout


def test_rename_carries_lac_local(make_git_repo, run_lac, lac_home):
    from lac.slugdir import read_local_path

    repo = make_git_repo("proj")
    run_lac("register", cwd=repo)
    run_lac("rename", "pretty-name", cwd=repo)
    new_slug = lac_home / "pretty-name"
    assert read_local_path(new_slug) == repo.resolve()
