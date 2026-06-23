"""lac CLI entry point."""

import os
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import questionary
import rich_click as click
from rich.table import Table

from . import __version__, console
from .checks import (
    check_exclude_block_integrity,
    check_slug_extra_files,
    check_slug_missing_files,
    check_symlink,
    check_symlink_targets,
)
from .gitutil import (
    LacHomeGitStatus,
    append_exclude,
    git_remote_url,
    is_git_repo,
    is_tracked,
    lac_home_git_status,
    remove_exclude,
    write_slug_pointer,
)
from .home import ensure_lac_home, get_lac_home
from .link import make_symlink, unlink_safely
from .meta import Meta
from .slugdir import get_slug_dir, init_slug_dir, read_local_path, write_local_path
from .template import AGENT_CONFIG_FILES

_DecisionAction = Literal["link", "keep_link", "skip", "skip_tracked", "already_linked", "abort"]

_SlugStatus = Literal[
    "ok",
    "broken",
    "orphan",
    "corrupted",
    "extra",
    "missing",
    "exclude-drift",
    "not-on-this-machine",
]


@dataclass
class _Decision:
    name: str
    action: _DecisionAction


@click.group()
@click.version_option(version=__version__, prog_name="lac")
def main() -> None:
    """Manage AI agent config files (CLAUDE.md, AGENTS.md, .mcp.json) across repos and machines."""
    ensure_lac_home()


def _copy_into_slug(src: Path, dst: Path) -> None:
    """Copy `src` (file or dir) into `dst`, replacing dst's existing entry.

    Args:
        src: Source file or directory.
        dst: Destination path; replaced if it already exists.
    """
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _populate_slug_entry(slug_dir: Path, name: str) -> None:
    """Create `slug_dir/name` from the template when known, else an empty file.

    For `AGENT_CONFIG_FILES` the entry is copied from `<lac_home>/_template/<name>`
    preserving file vs. directory type. For other names an empty file is created.

    Args:
        slug_dir: Slug directory under lac home.
        name: Entry name (basename) to create in the slug.
    """
    target = slug_dir / name
    template_entry = get_lac_home() / "_template" / name
    if name in AGENT_CONFIG_FILES and template_entry.exists():
        if template_entry.is_dir():
            shutil.copytree(template_entry, target)
        else:
            shutil.copy2(template_entry, target)
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()


def _prompt_existing(link_path: Path) -> Literal["keep", "skip", "abort"]:
    """Prompt the user for an untracked existing entry (C2 policy).

    In non-interactive mode (env `LAC_NONINTERACTIVE=1`), auto-skip.

    Args:
        link_path: Path of the existing untracked entry in the repo.

    Returns:
        One of "keep", "skip", "abort".
    """
    if os.environ.get("LAC_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        console.skip(link_path.name, "skipped (non-interactive mode)")
        return "skip"

    size_str = f" ({link_path.stat().st_size} bytes)" if link_path.is_file() else ""
    console.warn(f"Found existing untracked {link_path.name}{size_str}.")
    c = console.console()
    c.print("  [k]eep (copy to lac storage, link from repo)", markup=False)
    c.print("  [s]kip this file", markup=False)
    c.print("  [a]bort", markup=False)
    raw = click.prompt(
        "Choice [k/s/a]",
        type=click.Choice(["k", "s", "a"]),
        show_choices=False,
    )
    if raw == "k":
        return "keep"

    if raw == "a":
        return "abort"

    return "skip"


def _classify(
    cwd: Path, slug_dir: Path, name: str
) -> Literal["already_linked", "skip_tracked", "untracked", "link"]:
    """Classify what action is needed for one entry without prompting.

    Args:
        cwd: Repo working directory.
        slug_dir: Slug directory under lac home.
        name: Entry name relative to `cwd` and `slug_dir`.

    Returns:
        - "already_linked" — cwd link points to slug target.
        - "skip_tracked"  — exists in cwd and tracked by git.
        - "untracked"     — exists in cwd, untracked (needs user decision).
        - "link"          — does not exist in cwd (auto-link).
    """
    target = slug_dir / name
    link_path = cwd / name

    if link_path.is_symlink():
        try:
            current_target = (link_path.parent / os.readlink(link_path)).resolve()
            if current_target == target.resolve():
                return "already_linked"
        except OSError:
            pass

    if link_path.exists() or link_path.is_symlink():
        if is_tracked(cwd, name):
            return "skip_tracked"

        return "untracked"

    return "link"


def _decide(cwd: Path, slug_dir: Path, name: str) -> _Decision:
    """Determine the action for one entry without writing to the filesystem.

    Prompts the user only when needed (existing untracked file).

    Args:
        cwd: Repo working directory.
        slug_dir: Slug directory under lac home.
        name: Entry name relative to `cwd` and `slug_dir`.

    Returns:
        Decision describing the action to apply.
    """
    target = slug_dir / name
    link_path = cwd / name

    # Already correctly linked → idempotent.
    if link_path.is_symlink():
        try:
            current_target = (link_path.parent / os.readlink(link_path)).resolve()
            if current_target == target.resolve():
                return _Decision(name, "already_linked")
        except OSError:
            pass

    if link_path.exists() or link_path.is_symlink():
        if is_tracked(cwd, name):
            return _Decision(name, "skip_tracked")

        choice = _prompt_existing(link_path)
        if choice == "skip":
            return _Decision(name, "skip")

        if choice == "abort":
            return _Decision(name, "abort")

        return _Decision(name, "keep_link")

    return _Decision(name, "link")


def _apply_one(cwd: Path, slug_dir: Path, decision: _Decision) -> bool:
    """Apply a single Decision.

    Caller is responsible for handling `abort` decisions before calling this.

    Args:
        cwd: Repo working directory.
        slug_dir: Slug directory under lac home.
        decision: Decision produced by `_decide`.

    Returns:
        True if the entry ends up linked, False if skipped.
    """
    name = decision.name
    target = slug_dir / name
    link_path = cwd / name

    if decision.action == "already_linked":
        console.skip(name, "already linked")
        return True

    if decision.action == "skip_tracked":
        console.skip(
            name,
            f"tracked by git — to manage: `git rm --cached {name}` first",
        )
        return False

    if decision.action == "skip":
        return False

    if decision.action == "abort":
        raise RuntimeError("abort action should be handled by caller")  # pragma: no cover

    if decision.action == "keep_link":
        _copy_into_slug(link_path, target)
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()
        make_symlink(target, link_path)
        console.ok(f"{name} linked")
        return True

    if decision.action == "link":
        make_symlink(target, link_path)
        console.ok(f"{name} linked")
        return True

    raise ValueError(f"unknown action: {decision.action}")  # pragma: no cover


def _adoptable_slugs(home: Path, cwd: Path) -> list[tuple[Path, Meta]]:
    """Return active slugs whose recorded `repo_path` does not exist locally.

    Such slugs were registered on another machine and synced here, so they
    are adoption candidates when registering an otherwise-unmatched repo.
    Basename matches with `cwd` are ordered first.

    Args:
        home: lac home directory.
        cwd: Repo working directory being registered.

    Returns:
        List of (slug directory, meta), basename matches first.
    """
    candidates: list[tuple[Path, Meta]] = []
    for entry, meta in _iter_slugs(home):
        if meta is None:
            continue
        # No `.lac.local` => not bound on this machine => an adoption candidate.
        if read_local_path(entry) is None:
            candidates.append((entry, meta))
    # Order basename matches first. Assumes the `{name}-{hash6}` slug convention;
    # a renamed slug without a trailing `-hash` just sorts lower (list unaffected).
    candidates.sort(key=lambda c: c[0].name.rsplit("-", 1)[0] != cwd.name)
    return candidates


def _prompt_adopt(cwd: Path, candidates: list[tuple[Path, Meta]]) -> Path | Literal["new", "abort"]:
    """Prompt the user to adopt an existing slug or create a new one.

    Args:
        cwd: Repo working directory being registered.
        candidates: Adoptable slugs from `_adoptable_slugs`.

    Returns:
        Slug directory to adopt, "new" to create fresh, or "abort".
    """
    console.warn(f"'{cwd.name}' is not registered. Found storage from another machine:")
    c = console.console()
    for i, (entry, meta) in enumerate(candidates, 1):
        c.print(
            f"  [{i}] {entry.name}  ({meta.repo_remote or 'no remote'}, "
            f"{len(meta.linked_files)} linked)",
            markup=False,
        )
    c.print("  [n] create new storage", markup=False)
    c.print("  [a] abort", markup=False)
    choices = [str(i) for i in range(1, len(candidates) + 1)] + ["n", "a"]
    raw = click.prompt("Choice", type=click.Choice(choices), show_choices=False)
    if raw == "a":
        return "abort"
    if raw == "n":
        return "new"
    return candidates[int(raw) - 1][0]


def _adopt_slug(slug_dir: Path, cwd: Path) -> None:
    """Bind `cwd` to an existing `slug_dir`: update meta remote + write pointers.

    Args:
        slug_dir: Slug directory to adopt.
        cwd: Repo working directory claiming the slug.
    """
    meta_path = slug_dir / ".lac.meta"
    meta = Meta.load_safe(meta_path)
    if meta is not None:
        meta.repo_remote = git_remote_url(cwd)
        meta.save(meta_path)
    write_slug_pointer(cwd, slug_dir.name)
    write_local_path(slug_dir, cwd)


@main.command(epilog="Example: cd <git-repo> && lac register && lac link")
def register() -> None:
    """Register the current repo.

    When the repo is not matched but storage from another machine exists,
    offers to connect to it instead of creating a new one. Then run
    'lac link' to link agent config files.
    """
    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    ensure_lac_home()
    slug_dir = get_slug_dir(cwd)

    if not slug_dir.exists():
        candidates = _adoptable_slugs(get_lac_home(), cwd)
        interactive = os.environ.get("LAC_NONINTERACTIVE") != "1" and sys.stdin.isatty()
        if candidates and interactive:
            choice = _prompt_adopt(cwd, candidates)
            if choice == "abort":
                console.info("aborted (no changes)")
                sys.exit(1)
            if choice != "new":
                _adopt_slug(choice, cwd)
                console.ok(f"connected to {choice}")
                console.info("run 'lac link' to link agent config files in this repo")
                return

    slug_dir = init_slug_dir(cwd)
    console.ok(f"registered at {slug_dir}")
    console.info("run 'lac link' to link agent config files in this repo")


def _validate_link_arg(file: str) -> str | None:
    """Validate a relative path argument for `lac link` / `lac path`.

    Args:
        file: User-supplied file argument.

    Returns:
        Error message if invalid, None otherwise.
    """
    if Path(file).is_absolute():
        return f"'{file}' must be a relative path"

    if ".." in Path(file).parts:
        return f"'{file}' cannot contain '..'"

    if file.startswith("/") or file == "":
        return f"'{file}' is not a valid file name"

    return None


_LinkAction = Literal["link", "keep_link", "skip", "skip_tracked"]

_LAC_QUESTIONARY_STYLE = questionary.Style(
    [
        ("qmark", "noinherit bold"),
        ("question", "noinherit"),
        ("pointer", "noinherit bold"),
        ("highlighted", "noinherit bold"),
        ("selected", "noinherit"),
        ("checkbox", "noinherit"),
        ("checkbox-selected", "noinherit"),
        ("instruction", "noinherit"),
        ("answer", "noinherit"),
        ("text", "noinherit"),
        ("disabled", "noinherit"),
    ]
)


def _link_bulk(
    cwd: Path,
    slug_dir: Path,
    meta: Meta,
    meta_path: Path,
    *,
    force_select_all: bool,
) -> None:
    """Drive the bulk `lac link` flow over AGENT_CONFIG_FILES + custom entries.

    When ``force_select_all`` is True (the ``--all`` flag), every candidate is
    treated as checked without prompting. Otherwise the user picks via a
    questionary checkbox; non-interactive mode exits with code 1 and a hint to
    use ``--all`` or pass an explicit file.

    Two-phase: decide (checkbox/auto-select + conflict prompts, no FS writes) →
    apply (symlinks + meta + exclude). User abort during decide leaves the FS
    unchanged.

    Args:
        cwd: Repo working directory.
        slug_dir: Slug directory under lac home.
        meta: Loaded lac meta for the slug.
        meta_path: Path of the meta file (for saving updates).
        force_select_all: Skip the checkbox and select every candidate.
    """
    custom_files = [f for f in meta.linked_files if f not in AGENT_CONFIG_FILES]
    candidates: list[str] = [*AGENT_CONFIG_FILES, *custom_files]

    pre_checked: set[str] = set()
    for name in candidates:
        if (slug_dir / name).exists() and _classify(cwd, slug_dir, name) == "already_linked":
            pre_checked.add(name)

    if force_select_all:
        selected: set[str] = set(candidates)
    elif os.environ.get("LAC_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        console.error("non-interactive mode requires --all or an explicit file argument")
        console.info("run 'lac link --all' to link every agent config file, or 'lac link <file>'")
        sys.exit(1)
    else:
        choices = [
            questionary.Choice(
                f"{name} (linked)" if name in pre_checked else name,
                value=name,
                checked=(name in pre_checked),
            )
            for name in candidates
        ]
        result = questionary.checkbox(
            "Files to link:",
            choices=choices,
            instruction="(Space to toggle, Enter to confirm, Esc to abort)",
            style=_LAC_QUESTIONARY_STYLE,
        ).ask()
        if result is None:
            console.info("aborted (no changes)")
            return

        selected = set(result)

    to_link_raw = [n for n in candidates if n in selected and n not in pre_checked]
    to_unlink = [n for n in candidates if n not in selected and n in pre_checked]

    link_actions: list[tuple[str, _LinkAction]] = []
    for name in to_link_raw:
        cls = _classify(cwd, slug_dir, name)
        if cls == "skip_tracked":
            link_actions.append((name, "skip_tracked"))
            continue

        if cls == "untracked":
            choice = _prompt_existing(cwd / name)
            if choice == "abort":
                console.info("aborted (no changes)")
                return

            if choice == "skip":
                link_actions.append((name, "skip"))
            else:
                link_actions.append((name, "keep_link"))
            continue

        link_actions.append((name, "link"))

    unlinked_names: list[str] = []
    for name in to_unlink:
        try:
            unlink_safely(cwd / name, expected_target=slug_dir / name)
        except FileExistsError as e:
            console.warn(str(e))
            continue

        if name in meta.linked_files:
            meta.linked_files.remove(name)
        if name not in meta.unlinked_files:
            meta.unlinked_files.append(name)
        unlinked_names.append(name)
        console.ok(f"{name} unlinked")

    linked_names: list[str] = []
    for name, action in link_actions:
        if action == "skip_tracked":
            console.skip(name, f"tracked by git — run 'git rm --cached {name}' first")
            continue

        if action == "skip":
            console.skip(name, "skipped")
            continue

        target = slug_dir / name
        link_path = cwd / name
        if action == "keep_link":
            _copy_into_slug(link_path, target)
            if link_path.is_dir() and not link_path.is_symlink():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
            make_symlink(target, link_path)
        else:
            if not target.exists():
                _populate_slug_entry(slug_dir, name)
            try:
                make_symlink(target, link_path)
            except (FileExistsError, OSError) as e:
                console.error(f"{name}: {e}")
                continue

        if name not in meta.linked_files:
            meta.linked_files.append(name)
        if name in meta.unlinked_files:
            meta.unlinked_files.remove(name)
        linked_names.append(name)
        console.ok(f"{name} linked")

    if linked_names:
        try:
            append_exclude(cwd, linked_names)
        except OSError as e:
            console.error(f"cannot write .git/info/exclude: {e}")
    if unlinked_names:
        try:
            remove_exclude(cwd, unlinked_names)
        except OSError as e:
            console.error(f"cannot write .git/info/exclude: {e}")

    meta.save(meta_path)


@main.command(
    epilog=(
        "Examples:"
        "\n  lac link                  # checkbox over agent config files"
        "\n  lac link --all            # link every agent config file non-interactively"
        "\n  lac link CONTRIBUTING.md  # link one specific file"
    )
)
@click.argument("file", required=False)
@click.option(
    "--all",
    "all_",
    is_flag=True,
    help="Link all agent config files, no prompts.",
)
def link(file: str | None, all_: bool) -> None:
    """Link agent config files to lac storage.

    Without arguments, opens an interactive checkbox to toggle each file
    on/off. Use --all to link everything at once, or pass a single file
    to link just that one.
    """
    if all_ and file is not None:
        console.error("--all is mutually exclusive with an explicit file argument")
        sys.exit(1)

    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    slug_dir = get_slug_dir(cwd)
    if not slug_dir.exists():
        console.error("not registered")
        console.info("run 'lac register' first")
        sys.exit(1)

    meta_path = slug_dir / ".lac.meta"
    meta = Meta.load_safe(meta_path)
    if meta is None:
        console.error(f"lac state corrupted or missing at {meta_path}")
        console.info("run 'lac doctor' or manual cleanup")
        sys.exit(1)

    if all_:
        _link_bulk(cwd, slug_dir, meta, meta_path, force_select_all=True)
        return

    if file is None:
        _link_bulk(cwd, slug_dir, meta, meta_path, force_select_all=False)
        return

    err = _validate_link_arg(file)
    if err:
        console.error(err)
        sys.exit(1)

    if file in meta.linked_files and (cwd / file).is_symlink():
        console.info(f"{file} already linked")
        return

    target = slug_dir / file
    if not target.exists():
        _populate_slug_entry(slug_dir, file)

    decision = _decide(cwd, slug_dir, file)
    if decision.action == "abort":
        console.info("aborted (no changes)")
        sys.exit(1)

    try:
        if not _apply_one(cwd, slug_dir, decision):
            return
    except FileExistsError as e:
        console.error(f"{file}: {e}")
        sys.exit(1)
    except OSError as e:
        console.error(f"{file}: {e}")
        sys.exit(1)

    append_exclude(cwd, [file])
    if file not in meta.linked_files:
        meta.linked_files.append(file)
    if file in meta.unlinked_files:
        meta.unlinked_files.remove(file)
    meta.save(meta_path)


def _confirm_destroy(slug_dir: Path, n_files: int) -> bool:
    """Ask the user before destroying slug contents.

    In non-interactive mode (env `LAC_NONINTERACTIVE=1`), refuses without prompting.

    Args:
        slug_dir: Slug directory that would be destroyed.
        n_files: Number of linked files inside the slug.

    Returns:
        True if the user confirmed, False otherwise.
    """
    if os.environ.get("LAC_NONINTERACTIVE") == "1" or not sys.stdin.isatty():
        console.error("non-interactive: refusing to delete storage. Use --yes to confirm.")
        return False

    console.warn(
        f"This will DELETE '{slug_dir.name}' ({n_files} managed entries + your edits inside)."
    )
    return click.confirm("Continue?", default=False)


@main.command(epilog="Example: lac unregister --yes")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def unregister(yes: bool) -> None:
    """Unregister the current repo.

    Restores linked files into the repo. Storage is archived as a
    .bak.{timestamp} directory under lac home.
    """
    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    slug_dir = get_slug_dir(cwd)
    if not slug_dir.exists():
        console.error("not registered")
        console.info("run 'lac register' first")
        sys.exit(1)

    meta = Meta.load_safe(slug_dir / ".lac.meta")
    if meta is None:
        console.error(f"lac state corrupted or missing at {slug_dir / '.lac.meta'}")
        console.info(f"manual cleanup: rm -rf {slug_dir}")
        sys.exit(1)

    # Pre-validation: each cwd/name must be (a) our managed link, (b) missing in repo,
    # or (c) link to a slug file that's already gone (restore loop will skip it).
    for name in meta.linked_files:
        link_path = cwd / name
        if not link_path.exists() and not link_path.is_symlink():
            continue
        reason = check_symlink(cwd, slug_dir, name)
        if reason in (None, "target missing"):
            continue

        console.error(f"{name}: {reason} — refusing")
        console.info("run 'lac doctor' to inspect")
        sys.exit(1)

    if not yes and not _confirm_destroy(slug_dir, len(meta.linked_files)):
        console.info("aborted")
        return

    # Remove symlinks.
    for name in meta.linked_files:
        try:
            unlink_safely(cwd / name, expected_target=slug_dir / name)
        except FileExistsError as e:
            console.warn(str(e))

    remove_exclude(cwd, meta.linked_files)

    # Restore: copy slug content back to cwd (best-effort).
    restored: list[str] = []
    restore_failed: list[str] = []
    for name in meta.linked_files:
        src = slug_dir / name
        dst = cwd / name
        if not src.exists():
            continue

        try:
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            restored.append(name)
        except OSError as e:
            console.error(f"{name}: restore failed ({e})")
            restore_failed.append(name)

    # Backup slug. Append -2, -3, ... when same-second backups already exist.
    ts = datetime.now().strftime("%y%m%d-%H%M%S")
    bak_path = slug_dir.parent / f"{slug_dir.name}.bak.{ts}"
    for suffix in range(2, 101):
        if not bak_path.exists():
            break
        bak_path = slug_dir.parent / f"{slug_dir.name}.bak.{ts}-{suffix}"
    else:  # pragma: no cover
        console.error(f"too many backups for {slug_dir.name} at {ts}")
        sys.exit(1)
    slug_dir.rename(bak_path)

    summary = f"unregistered. restored {len(restored)} files. backup: {bak_path}"
    if restore_failed:
        summary += f" ({len(restore_failed)} restore failed: {', '.join(restore_failed)})"
    if meta.unlinked_files:
        summary += f" (unlinked preserved in backup: {', '.join(meta.unlinked_files)})"
    console.ok(summary)


def _iter_slugs(home: Path) -> Iterator[tuple[Path, Meta | None]]:
    """Yield (entry, meta) for each non-skip directory under lac home.

    Skips ``_<name>`` / ``.<name>`` / ``*.bak.*`` directories. Yields
    ``meta=None`` when ``.lac.meta`` is missing or unparseable so callers
    decide how to classify (corrupted vs skip).

    Args:
        home: lac home directory.

    Yields:
        Tuple of (entry path, parsed Meta or None).
    """
    for entry in sorted(home.iterdir()):
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        if ".bak." in entry.name:
            continue

        meta_path = entry / ".lac.meta"
        if not meta_path.exists():
            yield entry, None
            continue

        yield entry, Meta.load_safe(meta_path)


@main.command(name="list")
def list_() -> None:
    """List all registered repos and their state."""
    home = get_lac_home()
    if not home.exists():  # pragma: no cover
        console.info("no registered repos")
        return

    rows: list[tuple[str, str, str, str]] = []
    for entry, meta in _iter_slugs(home):
        if meta is None:
            continue

        local = read_local_path(entry)
        if local is None:
            status, repo_path = "not-on-this-machine", "(other machine)"
        elif not local.exists():
            status, repo_path = "orphan", str(local)
        else:
            status, repo_path = "ok", str(local)
        rows.append((entry.name, repo_path, str(len(meta.linked_files)), status))

    if not rows:
        console.info("no registered repos")
        return

    table = Table(show_header=True, box=None)
    table.add_column("name", style="cyan")
    table.add_column("repo_path")
    table.add_column("#linked", justify="right")
    table.add_column("status")
    for slug_name, repo_path, n, status in rows:
        if status == "orphan":
            style = "red"
        elif status == "not-on-this-machine":
            style = "yellow"
        else:
            style = ""
        table.add_row(slug_name, repo_path, n, f"[{style}]{status}[/{style}]" if style else status)
    console.console().print(table)


@main.command(epilog="Example: cd $(lac home) && git push")
def home() -> None:
    """Print the lac storage root directory."""
    click.echo(str(get_lac_home()))


@main.command()
def doctor() -> None:
    """Check all registered repos for issues.

    Diagnoses only — no auto-fix.
    """
    home = get_lac_home()
    if not home.exists():  # pragma: no cover
        console.info("no lac home — nothing to check")
        return

    rows: list[tuple[str, _SlugStatus, str]] = []
    ok_count = 0
    issue_count = 0
    other_count = 0
    found_statuses: set[_SlugStatus] = set()

    backup_count = sum(1 for entry in home.iterdir() if entry.is_dir() and ".bak." in entry.name)

    for entry, meta in _iter_slugs(home):
        if meta is None:
            rows.append((entry.name, "corrupted", "missing or unparseable .lac.meta"))
            issue_count += 1
            found_statuses.add("corrupted")
            continue

        local = read_local_path(entry)
        if local is None:
            rows.append((entry.name, "not-on-this-machine", "registered on another machine"))
            other_count += 1
            found_statuses.add("not-on-this-machine")
            continue

        repo_path = local
        if not repo_path.exists():
            rows.append((entry.name, "orphan", f"repo gone: {repo_path}"))
            issue_count += 1
            found_statuses.add("orphan")
            continue

        broken_findings = check_symlink_targets(repo_path, meta, entry)
        missing_findings = check_slug_missing_files(repo_path, meta, entry)
        extra_findings = check_slug_extra_files(repo_path, meta, entry)
        exclude_findings = check_exclude_block_integrity(repo_path, meta, entry)

        parts: list[str] = []
        if broken_findings:
            parts.append("broken: " + "; ".join(f.message for f in broken_findings))
        if missing_findings:
            parts.append("missing: " + ", ".join(f.message for f in missing_findings))
        if extra_findings:
            parts.append("extra: " + ", ".join(f.message for f in extra_findings))
        if exclude_findings:
            parts.append("exclude-drift")

        if broken_findings:
            status: _SlugStatus = "broken"
        elif missing_findings:
            status = "missing"
        elif extra_findings:
            status = "extra"
        elif exclude_findings:
            status = "exclude-drift"
        else:
            status = "ok"

        if status == "ok":
            rows.append((entry.name, "ok", ""))
            ok_count += 1
        else:
            rows.append((entry.name, status, "; ".join(parts)))
            issue_count += 1
            found_statuses.add(status)

    if not rows and backup_count == 0:
        console.info("no registered repos")
        return

    if rows:
        table = Table(show_header=True, box=None)
        table.add_column("name", style="cyan")
        table.add_column("status")
        table.add_column("detail")
        for slug_name, status, detail in rows:
            if status == "ok":
                style = "green"
            elif status == "not-on-this-machine":
                style = "yellow"
            else:
                style = "red"
            table.add_row(slug_name, f"[{style}]{status}[/{style}]", detail)
        console.console().print(table)

    summary = f"{ok_count} ok, {issue_count} issues found"
    if other_count:
        summary += f", {other_count} on other machines"
    if backup_count:
        summary += f", {backup_count} backup dir(s)"
    console.info(summary)

    if found_statuses or backup_count:
        hints: list[str] = []
        if "orphan" in found_statuses:
            hints.append("  - orphan: repo bound here is gone; restore it or `lac unregister`")
        if "not-on-this-machine" in found_statuses:
            hints.append(
                "  - not-on-this-machine: registered elsewhere; "
                "run `lac register` in the repo here to activate"
            )
        if "corrupted" in found_statuses:
            hints.append("  - corrupted: rm -rf $(lac home)/<name>")
        if "broken" in found_statuses:
            hints.append("  - broken: cd <repo> && lac unregister && lac register")
        if "missing" in found_statuses:
            hints.append("  - missing: file recorded but not in storage; restore or unregister")
        if "extra" in found_statuses:
            hints.append("  - extra: file in storage without record; run `lac link <file>`")
        if "exclude-drift" in found_statuses:
            hints.append(
                "  - exclude-drift: cd <repo> && lac unregister --yes && lac register "
                "&& lac link --all"
            )
        if backup_count:
            hints.append("  - backup cleanup: rm -rf $(lac home)/*.bak.*")
        if hints:
            console.info("Suggested actions:")
            for h in hints:
                console.console().print(h, markup=False)


_RESERVED_SLUG_NAMES = {"_template"}


def _validate_slug_name(name: str) -> str | None:
    """Validate a slug name argument for `lac rename`.

    Args:
        name: User-supplied slug name.

    Returns:
        Error message if invalid, None otherwise.
    """
    if not name:
        return "storage name cannot be empty"

    if "/" in name:
        return f"'{name}' is not a valid slug name (cannot contain '/')"

    if name.startswith(".") or name.startswith("_"):
        return f"'{name}' is reserved (cannot start with '.' or '_')"

    if name in _RESERVED_SLUG_NAMES:  # pragma: no cover
        return f"'{name}' is a reserved slug name"

    return None


@main.command(epilog="Example: lac rename my-django")
@click.argument("new_name")
def rename(new_name: str) -> None:
    """Rename the current repo's storage directory.

    Links in the repo update automatically to point at the new name.
    """
    err = _validate_slug_name(new_name)
    if err:
        console.error(err)
        sys.exit(1)

    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    old_slug = get_slug_dir(cwd)
    if not old_slug.exists():
        console.error("not registered")
        sys.exit(1)

    new_slug = old_slug.parent / new_name
    if new_slug.exists():
        console.error(f"'{new_name}' already exists at {new_slug}")
        console.info("choose a different name or remove the existing storage manually")
        sys.exit(1)

    meta = Meta.load_safe(old_slug / ".lac.meta")
    if meta is None:
        console.error(f"lac state corrupted at {old_slug / '.lac.meta'}")
        console.info("run 'lac doctor' or remove the storage manually")
        sys.exit(1)

    # Validate each linked entry is a managed link into old_slug or missing; abort otherwise.
    retarget_names: list[str] = []
    for name in meta.linked_files:
        link_path = cwd / name
        if not link_path.exists() and not link_path.is_symlink():
            continue
        reason = check_symlink(cwd, old_slug, name)
        if reason is not None and reason != "target missing":
            console.error(f"{name}: {reason} — refusing")
            console.info("run 'lac doctor' to inspect")
            sys.exit(1)

        retarget_names.append(name)

    # Rename the slug directory and retarget validated symlinks.
    old_slug.rename(new_slug)
    for name in retarget_names:
        link_path = cwd / name
        link_path.unlink()
        try:
            make_symlink(new_slug / name, link_path)
        except (FileExistsError, OSError) as e:
            console.error(f"{name}: failed to retarget — {e}")

    write_slug_pointer(cwd, new_name)
    write_local_path(new_slug, cwd)
    console.ok(f"renamed to {new_name}")


@main.command(epilog="Example: cd $(lac path) && cat $(lac path CLAUDE.md)")
@click.argument("file", required=False)
def path(file: str | None) -> None:
    """Print the storage path for the current repo (or for a specific file)."""
    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    slug_dir = get_slug_dir(cwd)
    if not slug_dir.exists():
        console.error("not registered")
        console.info("run 'lac register' first")
        sys.exit(1)

    if file is None:
        click.echo(str(slug_dir))
        return

    err = _validate_link_arg(file)
    if err:
        console.error(err)
        sys.exit(1)

    click.echo(str(slug_dir / file))


def _format_lac_home_git(s: LacHomeGitStatus) -> str:
    """Render a `LacHomeGitStatus` snapshot in POLICY §3.2 mockup form."""
    branch = s.branch or "(detached)"
    if s.merging:
        n = len(s.conflict_paths)
        suffix = f"⚠ MERGING ({n} conflicts)" if n else "⚠ MERGING"
        return f"{branch} · {suffix}"
    tokens: list[str] = []
    if s.uncommitted_count:
        tokens.append(f"{s.uncommitted_count} uncommitted")
    if s.ahead:
        tokens.append(f"{s.ahead} ahead")
    if s.behind:
        tokens.append(f"{s.behind} behind")
    if not tokens:
        tokens.append("clean")
    return f"{branch} · " + " · ".join(tokens)


@main.command()
def status() -> None:
    """Show registration state of the current repo."""
    cwd = Path.cwd()
    if not is_git_repo(cwd):
        console.error("not a git repository")
        console.info("run from inside a git repository — try 'cd <repo>' or 'git init'")
        sys.exit(1)

    slug_dir = get_slug_dir(cwd)
    if not slug_dir.exists():
        console.error("not registered")
        console.info("run 'lac register' first")
        sys.exit(1)

    meta = Meta.load_safe(slug_dir / ".lac.meta")
    if meta is None:
        console.error(f"lac state corrupted or missing at {slug_dir / '.lac.meta'}")
        console.info("run 'lac doctor' or remove the storage manually")
        sys.exit(1)

    table = Table(show_header=False, box=None)
    table.add_column("key", style="cyan")
    table.add_column("value")
    local = read_local_path(slug_dir)
    table.add_row("lac_home", str(get_lac_home()))
    table.add_row("name", slug_dir.name)
    table.add_row("storage_dir", str(slug_dir))
    table.add_row("repo_path", str(local) if local else "(not on this machine)")
    table.add_row("repo_remote", meta.repo_remote or "(none)")
    table.add_row("created_at", meta.created_at)
    table.add_row("linked_files", "\n".join(meta.linked_files) or "(none)")
    git_status = lac_home_git_status(get_lac_home())
    if git_status is not None:
        table.add_row("lac_home_git", _format_lac_home_git(git_status))
        if git_status.conflict_paths:
            table.add_row("lac_home_conflicts", "\n".join(git_status.conflict_paths))
    console.console().print(table)


def entry() -> None:
    """Wrap main with KeyboardInterrupt → exit 1 (graceful Ctrl+C)."""
    try:
        main()
    except KeyboardInterrupt:
        console.info("aborted")
        sys.exit(1)
