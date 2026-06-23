"""End-to-end tests covering the `lac` CLI surface.

Real filesystem, real git, real symlinks. No mocking — these exercise the same
behavior a user would see. Each test owns its own tmp_path and LAC_HOME via the
fixtures in `conftest.py`.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_CONFIG_FILES = ["CLAUDE.md", "AGENTS.md", ".claude", ".agents", ".cursorrules", ".mcp.json"]


@pytest.fixture
def registered_repo(make_git_repo, run_lac):
    """Repo after `lac register` + `lac link <name>` for every AGENT_CONFIG_FILES entry."""
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    for name in AGENT_CONFIG_FILES:
        run_lac("link", name, cwd=repo)
    return repo


@pytest.fixture
def slug_only_repo(make_git_repo, run_lac):
    """Repo after `lac register` with no files linked yet."""
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    return repo


def test_home_reflects_env_var(lac_home, run_lac, make_git_repo):
    repo = make_git_repo()
    cp = run_lac("home", cwd=repo)
    assert cp.stdout.strip() == str(lac_home)


def test_register_creates_slug_only_no_files_linked(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("register", cwd=repo)
    assert "registered at" in cp.stdout
    assert "lac link" in cp.stdout
    for name in AGENT_CONFIG_FILES:
        assert not (repo / name).exists(), f"{name} must not be linked by register"


def test_setup_appends_exclude_marker(registered_repo):
    exclude = registered_repo / ".git" / "info" / "exclude"
    contents = exclude.read_text()
    assert "lac:start" in contents
    assert "lac:end" in contents
    for name in AGENT_CONFIG_FILES:
        assert name in contents, f"{name} missing from exclude"


def test_status_shows_linked_files(registered_repo, run_lac):
    cp = run_lac("status", cwd=registered_repo)
    assert "linked_files" in cp.stdout
    for name in AGENT_CONFIG_FILES:
        assert name in cp.stdout, f"{name} missing from status"


def test_link_single_file_creates_symlink(registered_repo, run_lac, lac_home):
    run_lac("link", "CUSTOM.md", cwd=registered_repo)
    link = registered_repo / "CUSTOM.md"
    assert link.is_symlink()
    target = Path(link.resolve())
    assert target.exists()
    assert str(lac_home) in str(target)


def test_path_returns_slug_dir(registered_repo, run_lac):
    cp = run_lac("path", cwd=registered_repo)
    slug_dir = Path(cp.stdout.strip())
    assert slug_dir.is_dir()

    cp_file = run_lac("path", "CLAUDE.md", cwd=registered_repo)
    assert cp_file.stdout.strip() == str(slug_dir / "CLAUDE.md")


def _active_slug_dirs(lac_home: Path) -> list[Path]:
    """Slug dirs (name-hash), excluding `.bak.*` backups and `_template`."""
    return [
        p
        for p in lac_home.iterdir()
        if p.is_dir() and "-" in p.name and ".bak." not in p.name and p.name != "_template"
    ]


def test_list_counts_active_slugs(make_git_repo, run_lac, lac_home):
    repo1 = make_git_repo()
    repo2 = make_git_repo()
    run_lac("register", cwd=repo1)
    run_lac("register", cwd=repo2)
    assert len(_active_slug_dirs(lac_home)) == 2


def test_unregister_restores_files_and_creates_backup(registered_repo, run_lac, lac_home):
    run_lac("unregister", "--yes", cwd=registered_repo)

    for name in ("CLAUDE.md", "AGENTS.md"):
        p = registered_repo / name
        assert p.is_file() and not p.is_symlink(), f"{name} not restored as regular file"

    exclude = registered_repo / ".git" / "info" / "exclude"
    if exclude.exists():
        assert "lac:start" not in exclude.read_text()

    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    assert len(backups) == 1, [p.name for p in lac_home.iterdir()]


def test_list_hides_backup_directory(registered_repo, run_lac):
    run_lac("unregister", "--yes", cwd=registered_repo)
    cp = run_lac("list", cwd=registered_repo)
    assert "backup" not in cp.stdout
    assert ".bak." not in cp.stdout


def test_doctor_reports_healthy_slug(registered_repo, run_lac):
    cp = run_lac("doctor", cwd=registered_repo)
    assert "ok" in cp.stdout
    assert "0 issues" in cp.stdout or "0 issue" in cp.stdout


def test_rename_renames_slug_and_retargets_symlink(registered_repo, run_lac, lac_home):
    run_lac("rename", "pretty-name", cwd=registered_repo)
    assert (lac_home / "pretty-name").is_dir()

    target = (registered_repo / "CLAUDE.md").readlink()
    assert "pretty-name" in str(target)


def test_register_rejects_non_git_dir(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("register", cwd=non_git, check=False)
    assert cp.returncode == 1


def test_doctor_reports_corrupted_when_meta_file_missing(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").unlink()
    cp = run_lac("doctor", cwd=registered_repo)
    assert "corrupted" in cp.stdout


def test_doctor_reports_corrupted_when_meta_unparseable(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not valid yaml :::\n")
    cp = run_lac("doctor", cwd=registered_repo)
    assert "corrupted" in cp.stdout


def test_doctor_reports_orphan_when_bound_repo_gone(make_git_repo, run_lac, lac_home, tmp_path):
    repo = make_git_repo("doomed")
    run_lac("register", cwd=repo)  # writes .lac.local binding this machine
    shutil.rmtree(repo)

    # doctor reads lac home only; cwd just needs to exist.
    runner_cwd = tmp_path / "elsewhere"
    runner_cwd.mkdir()
    cp = run_lac("doctor", cwd=runner_cwd)
    assert "orphan" in cp.stdout
    assert "gone" in cp.stdout


def test_doctor_reports_missing_when_storage_file_missing(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / "CLAUDE.md").unlink()
    cp = run_lac("doctor", cwd=registered_repo)
    assert "missing" in cp.stdout
    assert "CLAUDE.md" in cp.stdout


def test_doctor_says_no_registered_repos_when_home_is_empty(tmp_path, run_lac, lac_home):
    lac_home.mkdir(parents=True)
    cp = run_lac("doctor", cwd=tmp_path)
    assert "no registered repos" in cp.stdout


def test_rename_rejects_name_containing_slash(registered_repo, run_lac):
    cp = run_lac("rename", "a/b", cwd=registered_repo, check=False)
    assert cp.returncode == 1


def test_rename_rejects_name_starting_with_underscore(registered_repo, run_lac):
    cp = run_lac("rename", "_hidden", cwd=registered_repo, check=False)
    assert cp.returncode == 1


def test_rename_in_non_git_dir_exits_one(tmp_path, run_lac):
    non_git = tmp_path / "plain"
    non_git.mkdir()
    cp = run_lac("rename", "foo", cwd=non_git, check=False)
    assert cp.returncode == 1


def test_rename_in_unregistered_repo_exits_one(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("rename", "foo", cwd=repo, check=False)
    assert cp.returncode == 1


def test_rename_rejects_name_already_taken_by_another_slug(make_git_repo, run_lac, lac_home):
    repo_a = make_git_repo("a")
    repo_b = make_git_repo("b")
    run_lac("register", cwd=repo_a)
    run_lac("register", cwd=repo_b)
    slug_a_name = next(p.name for p in _active_slug_dirs(lac_home) if p.name.startswith("a-"))
    cp = run_lac("rename", slug_a_name, cwd=repo_b, check=False)
    assert cp.returncode == 1


def test_status_when_meta_corrupted_exits_one(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac("status", cwd=registered_repo, check=False)
    assert cp.returncode == 1


def test_list_outputs_no_registered_repos_when_home_does_not_exist(tmp_path, run_lac):
    cp = run_lac("list", cwd=tmp_path)
    assert "no registered repos" in cp.stdout


def test_list_outputs_no_registered_repos_when_home_empty(tmp_path, run_lac, lac_home):
    lac_home.mkdir(parents=True)
    cp = run_lac("list", cwd=tmp_path)
    assert "no registered repos" in cp.stdout


def test_list_hides_directory_without_meta(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").unlink()
    cp = run_lac("list", cwd=registered_repo)
    assert slug.name not in cp.stdout
    assert "no registered repos" in cp.stdout


def test_list_hides_directory_with_unparseable_meta(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac("list", cwd=registered_repo)
    assert slug.name not in cp.stdout
    assert "no registered repos" in cp.stdout


def test_list_marks_orphan_when_repo_path_missing(make_git_repo, run_lac, lac_home, tmp_path):
    repo = make_git_repo("doomed-for-list")
    run_lac("register", cwd=repo)
    shutil.rmtree(repo)
    runner_cwd = tmp_path / "elsewhere-for-list"
    runner_cwd.mkdir()
    cp = run_lac("list", cwd=runner_cwd)
    assert "orphan" in cp.stdout


def test_list_shows_ok_status_for_registered_repo(registered_repo, run_lac):
    cp = run_lac("list", cwd=registered_repo)
    assert "ok" in cp.stdout


def test_link_is_idempotent_for_already_linked_file(registered_repo, run_lac):
    cp = run_lac("link", "CLAUDE.md", cwd=registered_repo)
    assert "already linked" in cp.stdout


def test_unregister_exits_one_when_meta_corrupted(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac("unregister", "--yes", cwd=registered_repo, check=False)
    assert cp.returncode == 1


def test_link_exits_one_when_meta_corrupted(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac("link", "NEW.md", cwd=registered_repo, check=False)
    assert cp.returncode == 1
    assert "corrupted" in cp.stdout.lower() or "corrupted" in cp.stderr.lower()
    assert "Traceback" not in cp.stderr
    assert "yaml" not in cp.stderr.lower()


def test_unregister_refuses_when_symlink_replaced_by_regular_file(registered_repo, run_lac):
    link = registered_repo / "CLAUDE.md"
    link.unlink()
    link.write_text("user replaced this\n")
    cp = run_lac("unregister", "--yes", cwd=registered_repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not a managed link" in output


def test_unregister_refuses_when_symlink_target_differs(
    registered_repo, run_lac, lac_home, tmp_path
):
    decoy = tmp_path / "decoy.md"
    decoy.write_text("decoy\n")
    link = registered_repo / "CLAUDE.md"
    link.unlink()
    link.symlink_to(decoy)

    slug_before = _active_slug_dirs(lac_home)[0]

    cp = run_lac("unregister", "--yes", cwd=registered_repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "wrong target" in output
    assert slug_before.is_dir()
    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    assert len(backups) == 0


def test_register_called_twice_is_idempotent(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    slugs_after_first = sorted(p.name for p in lac_home.iterdir() if p.is_dir() and "-" in p.name)
    run_lac("register", cwd=repo)
    slugs_after_second = sorted(p.name for p in lac_home.iterdir() if p.is_dir() and "-" in p.name)
    assert slugs_after_first == slugs_after_second


def test_unregister_tolerates_user_deleted_symlinks(registered_repo, run_lac):
    for name in AGENT_CONFIG_FILES:
        link = registered_repo / name
        if link.is_symlink():
            link.unlink()
    cp = run_lac("unregister", "--yes", cwd=registered_repo)
    assert cp.returncode == 0


def test_unregister_tolerates_missing_exclude_file(registered_repo, run_lac):
    (registered_repo / ".git/info/exclude").unlink()
    cp = run_lac("unregister", "--yes", cwd=registered_repo)
    assert cp.returncode == 0


def test_doctor_reports_broken_when_symlink_replaced_by_regular_file(registered_repo, run_lac):
    link = registered_repo / "CLAUDE.md"
    link.unlink()
    link.write_text("user replaced\n")
    cp = run_lac("doctor", cwd=registered_repo)
    assert "broken" in cp.stdout
    assert "not a managed link" in cp.stdout


def test_doctor_reports_broken_when_symlink_points_elsewhere(registered_repo, run_lac, tmp_path):
    link = registered_repo / "CLAUDE.md"
    link.unlink()
    decoy = tmp_path / "decoy.md"
    decoy.write_text("decoy\n")
    link.symlink_to(decoy)
    cp = run_lac("doctor", cwd=registered_repo)
    assert "broken" in cp.stdout
    assert "wrong target" in cp.stdout


def test_doctor_summarizes_backup_count_when_only_backups_present(
    make_git_repo, run_lac, lac_home, tmp_path
):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("unregister", "--yes", cwd=repo)
    runner_cwd = tmp_path / "elsewhere-backup-only"
    runner_cwd.mkdir()
    cp = run_lac("doctor", cwd=runner_cwd)
    assert "backup" in cp.stdout


def test_rename_exits_one_when_meta_corrupted(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac("rename", "newname", cwd=registered_repo, check=False)
    assert cp.returncode == 1


def test_rename_refuses_when_some_links_replaced_by_regular_files(
    registered_repo, run_lac, lac_home
):
    link = registered_repo / "CLAUDE.md"
    link.unlink()
    link.write_text("user file\n")

    slug_before = _active_slug_dirs(lac_home)[0]
    slug_name_before = slug_before.name
    other_links_before = {
        name: (registered_repo / name).resolve() for name in ("AGENTS.md", ".mcp.json")
    }

    cp = run_lac("rename", "pretty", cwd=registered_repo, check=False)

    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not a managed link" in output

    assert (lac_home / slug_name_before).is_dir()
    assert not (lac_home / "pretty").exists()
    for name, target_before in other_links_before.items():
        assert (registered_repo / name).resolve() == target_before


def test_rename_then_status_link_unregister_succeed_on_renamed_slug(
    registered_repo, run_lac, lac_home
):
    run_lac("rename", "renamed-slug", cwd=registered_repo)

    cp_status = run_lac("status", cwd=registered_repo)
    assert "renamed-slug" in cp_status.stdout

    run_lac("link", "NOTES.md", cwd=registered_repo)
    assert (lac_home / "renamed-slug" / "NOTES.md").exists()
    note_link = registered_repo / "NOTES.md"
    assert note_link.is_symlink()
    assert note_link.resolve().parent == (lac_home / "renamed-slug").resolve()

    run_lac("unregister", "--yes", cwd=registered_repo)
    backups = [
        p for p in lac_home.iterdir() if p.is_dir() and p.name.startswith("renamed-slug.bak.")
    ]
    assert len(backups) == 1


def test_rename_followed_by_register_does_not_create_second_slug(
    registered_repo, run_lac, lac_home
):
    run_lac("rename", "pretty", cwd=registered_repo)
    run_lac("register", cwd=registered_repo)
    active = [
        p
        for p in lac_home.iterdir()
        if p.is_dir()
        and not p.name.startswith("_")
        and not p.name.startswith(".")
        and ".bak." not in p.name
    ]
    assert [p.name for p in active] == ["pretty"]


def test_register_with_git_remote_uses_remote_based_slug_name(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/user/myrepo.git"],
        cwd=repo,
        check=True,
    )
    run_lac("register", cwd=repo)
    slugs = _active_slug_dirs(lac_home)
    assert len(slugs) == 1
    assert slugs[0].name.startswith("myrepo-")


def test_two_paths_same_remote_share_slug(make_git_repo, run_lac, lac_home):
    repo_a = make_git_repo("clone-a")
    repo_b = make_git_repo("clone-b")
    remote = "https://github.com/user/shared.git"
    for repo in (repo_a, repo_b):
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
    run_lac("register", cwd=repo_a)
    run_lac("register", cwd=repo_b)
    slugs = [p for p in lac_home.iterdir() if p.is_dir() and p.name.startswith("shared-")]
    assert len(slugs) == 1


def test_register_without_git_remote_falls_back_to_path_hash(make_git_repo, run_lac, lac_home):
    repo = make_git_repo("local-only")
    run_lac("register", cwd=repo)
    slugs = _active_slug_dirs(lac_home)
    assert len(slugs) == 1
    assert slugs[0].name.startswith("local-only-")


def test_setup_links_every_standard_file_in_repo(registered_repo):
    for name in AGENT_CONFIG_FILES:
        assert (registered_repo / name).is_symlink(), f"{name} should be linked"


def test_setup_adds_every_standard_file_to_exclude(registered_repo):
    exclude = (registered_repo / ".git/info/exclude").read_text()
    for name in AGENT_CONFIG_FILES:
        assert name in exclude, f"{name} should be in exclude"


def test_link_promotes_user_added_slug_file_to_repo(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", ".claude", cwd=repo)
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".claude" / "agent.md").write_text("agent content\n")
    assert (repo / ".claude").is_symlink()
    assert (repo / ".claude" / "agent.md").read_text() == "agent content\n"


def test_lac_link_all_links_every_standard_file(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("link", "--all", cwd=repo)
    for name in AGENT_CONFIG_FILES:
        assert (repo / name).is_symlink(), f"{name} not linked"
        assert name in cp.stdout, f"{name} not announced in output"
    slug = _active_slug_dirs(lac_home)[0]
    meta_text = (slug / ".lac.meta").read_text()
    for name in AGENT_CONFIG_FILES:
        assert name in meta_text


def test_lac_link_all_keeps_existing_custom_file(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    run_lac("link", "NOTES.md", cwd=repo)
    assert (repo / "NOTES.md").is_symlink()
    run_lac("link", "--all", cwd=repo)
    assert (repo / "NOTES.md").is_symlink()
    for name in AGENT_CONFIG_FILES:
        assert (repo / name).is_symlink()
    slug = _active_slug_dirs(lac_home)[0]
    meta_text = (slug / ".lac.meta").read_text()
    assert "NOTES.md" in meta_text


def test_lac_link_no_args_in_non_interactive_exits_one_with_hint(make_git_repo, run_lac):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = run_lac("link", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "--all" in output
    assert "non-interactive" in output


def test_lac_link_without_register_prints_run_register_hint(make_git_repo, run_lac):
    repo = make_git_repo()
    cp = run_lac("link", cwd=repo, check=False)
    assert cp.returncode == 1
    output = (cp.stdout + cp.stderr).lower()
    assert "not registered" in output
    assert "lac register" in output


@pytest.mark.parametrize(
    "cmd",
    ["register", "link", "unregister", "list", "status", "home", "path", "rename", "doctor"],
)
def test_help_text_uses_no_internal_jargon(cmd, run_lac, tmp_path):
    cp = run_lac(cmd, "--help", cwd=tmp_path, check=False)
    text = cp.stdout.lower()
    for jargon in ["slug", "metadata", "symlink"]:
        assert jargon not in text, f"jargon '{jargon}' found in `{cmd} --help`"


@pytest.mark.parametrize(
    "cmd_args",
    [
        ["status"],
        ["link", "FILE.md"],
        ["unregister", "--yes"],
        ["rename", "newname"],
    ],
)
def test_error_messages_use_no_internal_jargon(cmd_args, registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / ".lac.meta").write_text("::: not yaml :::\n")
    cp = run_lac(*cmd_args, cwd=registered_repo, check=False)
    output = (cp.stdout + cp.stderr).lower()
    for jargon in ["slug", "symlink"]:
        assert jargon not in output, f"jargon '{jargon}' in {cmd_args} output"
    # `.lac.meta` is the actual file path; exclude before checking the word "meta".
    # Rich may wrap long paths across lines on narrow terminals (CI 80-col).
    text_clean = re.sub(r"\.\s*lac\.\s*meta", "", output)
    assert "meta" not in text_clean, f"jargon 'meta' in {cmd_args} output"


@pytest.mark.parametrize("cmd_args", [["list"], ["status"], ["doctor"]])
def test_table_output_uses_no_internal_jargon(cmd_args, registered_repo, run_lac):
    cp = run_lac(*cmd_args, cwd=registered_repo)
    text = cp.stdout.lower()
    clean = re.sub(r"\.\s*lac\.\s*meta", "", text)
    for jargon in ["slug", "metadata", "symlink"]:
        assert jargon not in clean, f"jargon '{jargon}' in {cmd_args[0]}"


def test_doctor_reports_extra_when_file_in_storage_without_meta(registered_repo, run_lac, lac_home):
    slug = _active_slug_dirs(lac_home)[0]
    (slug / "NOTES.md").write_text("user-added content\n")
    cp = run_lac("doctor", cwd=registered_repo)
    assert "extra" in cp.stdout
    assert "NOTES.md" in cp.stdout


def test_query_command_reinitializes_git_when_dot_git_missing(registered_repo, run_lac, lac_home):
    shutil.rmtree(lac_home / ".git")
    assert not (lac_home / ".git").exists()
    run_lac("list", cwd=registered_repo)
    assert (lac_home / ".git").is_dir()


def test_version_does_not_initialize_lac_home(lac_home, run_lac, tmp_path):
    assert not lac_home.exists()
    run_lac("--version", cwd=tmp_path)
    assert not lac_home.exists()


def _run_with_stdin_devnull(args, cwd, lac_home):
    env = {
        **os.environ,
        "LAC_HOME": str(lac_home),
        "NO_COLOR": "1",
    }
    env.pop("LAC_NONINTERACTIVE", None)
    return subprocess.run(
        [sys.executable, "-m", "lac", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
    )


def test_register_in_non_tty_creates_slug_without_traceback(make_git_repo, lac_home):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")
    cp = _run_with_stdin_devnull(["register"], cwd=repo, lac_home=lac_home)
    assert cp.returncode == 0
    assert "registered at" in cp.stdout
    assert "Traceback" not in cp.stderr
    assert (repo / "CLAUDE.md").is_file()
    assert not (repo / "CLAUDE.md").is_symlink()


def test_unregister_in_non_tty_refuses_without_traceback(make_git_repo, run_lac, lac_home):
    repo = make_git_repo()
    run_lac("register", cwd=repo)
    cp = _run_with_stdin_devnull(["unregister"], cwd=repo, lac_home=lac_home)
    assert cp.returncode == 0
    output = (cp.stdout + cp.stderr).lower()
    assert "non-interactive" in output
    assert "refusing" in output
    assert "aborted" in output
    assert "Traceback" not in cp.stderr
    # FS unchanged (no backup created)
    backups = [p for p in lac_home.iterdir() if p.is_dir() and ".bak." in p.name]
    assert len(backups) == 0


def test_register_in_non_tty_does_not_touch_existing_files(make_git_repo, lac_home):
    repo = make_git_repo()
    (repo / "CLAUDE.md").write_text("user content\n")
    (repo / "AGENTS.md").write_text("agent content\n")
    cp = _run_with_stdin_devnull(["register"], cwd=repo, lac_home=lac_home)
    assert cp.returncode == 0
    assert "Traceback" not in cp.stderr
    assert (repo / "CLAUDE.md").read_text() == "user content\n"
    assert (repo / "AGENTS.md").read_text() == "agent content\n"
    assert not (repo / "CLAUDE.md").is_symlink()
    assert not (repo / "AGENTS.md").is_symlink()
