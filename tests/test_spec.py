"""Specification tests — one assertion per locked-in decision.

Each test maps to a row in CLAUDE.md's locked-decision table. When a decision
changes, the corresponding test changes; when a test fails, either the
implementation drifted or the decision needs an explicit update in CLAUDE.md.

Distinct from `test_e2e.py`, which exercises happy-path workflows end-to-end.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert slug_entries == {".lac.meta"}
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
