"""Git interaction helpers."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

LAC_MARK_START = "# === lac:start ==="
LAC_MARK_END = "# === lac:end ==="

CONFLICT_PREFIXES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})

LAC_HOME_IGNORE_PATTERNS = [
    "*.bak.*",
    ".DS_Store",
    ".idea/",
    ".vscode/",
    "*.swp",
    ".lac.local",
]


def is_git_repo(path: Path) -> bool:
    """Check whether `path` has a `.git` directory (or worktree pointer file).

    Args:
        path: Directory to inspect.

    Returns:
        True if `.git` exists under `path`, False otherwise.
    """
    return (path / ".git").exists()


def _normalize_remote_url(url: str) -> str:
    """Normalize a git remote URL for stable cross-machine identification.

    Strips scheme, user, and trailing `.git`; lowercases the result so that
    SSH and HTTPS forms of the same remote produce the same identifier.

    Args:
        url: Raw remote URL from `git remote get-url`.

    Returns:
        Lowercase normalized URL such as ``github.com/user/repo``.
    """
    s = url.strip()
    if s.startswith("git@"):
        rest = s[len("git@") :]
        host, _, path = rest.partition(":")
        s = f"{host}/{path}"
    else:
        for scheme in ("https://", "http://", "git://", "ssh://"):
            if s.startswith(scheme):
                s = s[len(scheme) :]
                if "@" in s.split("/", 1)[0]:
                    s = s.split("@", 1)[1]
                break

    if s.endswith(".git"):
        s = s[:-4]
    s = s.rstrip("/")
    return s.lower()


def git_remote_url(repo: Path) -> str | None:
    """Return the normalized origin remote URL, or None if unavailable.

    Args:
        repo: Repo working directory.

    Returns:
        Normalized URL on success, None if no remote or git command fails.
    """
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    return _normalize_remote_url(raw)


def is_tracked(repo: Path, rel: str) -> bool:
    """Check whether `rel` is tracked by git in `repo`.

    Args:
        repo: Repo working directory.
        rel: Path relative to `repo`.

    Returns:
        True if `rel` is tracked, False otherwise.
    """
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel],
        cwd=repo,
        capture_output=True,
    )
    return result.returncode == 0


def read_slug_pointer(repo: Path) -> str | None:
    """Return the slug name bound to `repo` via `.git/lac`, or None.

    The pointer is machine-local (lives under the repo's `.git`, never synced),
    so each machine records its own slug binding independently and survives
    repo directory moves.

    Args:
        repo: Repo working directory.

    Returns:
        Slug directory name on success, None when absent or unreadable.
    """
    try:
        name = (repo / ".git" / "lac").read_text().strip()
    except OSError:
        return None
    return name or None


def write_slug_pointer(repo: Path, slug_name: str) -> None:
    """Bind `repo` to `slug_name` by writing `.git/lac`. Best-effort.

    No-op when `.git` is not a directory (e.g. a git worktree pointer file).

    Args:
        repo: Repo working directory.
        slug_name: Slug directory name to record.
    """
    git_dir = repo / ".git"
    if not git_dir.is_dir():
        return
    (git_dir / "lac").write_text(slug_name + "\n")


def _exclude_path(repo: Path) -> Path:
    """Return the path of the `.git/info/exclude` file for `repo`."""
    return repo / ".git" / "info" / "exclude"


def split_block(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split lines into (before_block, block_entries, after_block).

    Args:
        lines: Lines of an exclude-style file (`.git/info/exclude` or `.gitignore`).

    Returns:
        Tuple of (lines before the lac block, entries inside, lines after).
        If no lac block is found, returns (lines, [], []).
    """
    try:
        start = lines.index(LAC_MARK_START)
        end = lines.index(LAC_MARK_END, start + 1)
    except ValueError:
        return lines, [], []

    return lines[:start], lines[start + 1 : end], lines[end + 1 :]


def append_exclude(repo: Path, entries: list[str]) -> None:
    """Add entries to the lac-managed block in `.git/info/exclude`. Idempotent.

    Args:
        repo: Repo working directory.
        entries: Entry names to add. Duplicates inside the block are skipped.
    """
    path = _exclude_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    before, block, after = split_block(existing)

    seen = set(block)
    for e in entries:
        if e not in seen:
            block.append(e)
            seen.add(e)

    new = list(before)
    if before and before[-1] != "":
        new.append("")
    new.append(LAC_MARK_START)
    new.extend(block)
    new.append(LAC_MARK_END)
    new.extend(after)

    path.write_text("\n".join(new) + "\n")


def apply_lac_home_gitignore(home: Path) -> None:
    """Write lac-managed ignore patterns into the lac home `.gitignore` marker block.

    Creates the file if absent. Preserves user lines outside the lac block.
    Overwrites the lac block contents with `LAC_HOME_IGNORE_PATTERNS` —
    user edits inside the block are not preserved. Re-running with the same
    patterns is a no-op (idempotent).

    Args:
        home: lac home directory.
    """
    path = home / ".gitignore"
    existing = path.read_text().splitlines() if path.exists() else []
    before, _, after = split_block(existing)

    new = list(before)
    if before and before[-1] != "":
        new.append("")
    new.append(LAC_MARK_START)
    new.extend(LAC_HOME_IGNORE_PATTERNS)
    new.append(LAC_MARK_END)
    new.extend(after)

    path.write_text("\n".join(new) + "\n")


def remove_exclude(repo: Path, entries: list[str]) -> None:
    """Remove entries from the lac block. Drop markers if the block becomes empty.

    Args:
        repo: Repo working directory.
        entries: Entry names to remove. Entries not in the block are ignored.
    """
    path = _exclude_path(repo)
    if not path.exists():
        return

    existing = path.read_text().splitlines()
    before, block, after = split_block(existing)
    if not block and LAC_MARK_START not in existing:
        return

    remaining = [e for e in block if e not in set(entries)]

    new = list(before)
    if remaining:
        if before and before[-1] != "":
            new.append("")
        new.append(LAC_MARK_START)
        new.extend(remaining)
        new.append(LAC_MARK_END)
    # drop trailing blank previously inserted
    while new and new[-1] == "":
        new.pop()
    new.extend(after)

    path.write_text(("\n".join(new) + "\n") if new else "")


@dataclass(frozen=True)
class LacHomeGitStatus:
    """Snapshot of lac home git state for display by `lac status`.

    Attributes:
        branch: Current branch name. Empty string on unborn HEAD or detached HEAD.
        uncommitted_count: Working tree changes excluding conflict-prefixed lines.
        ahead: Local commits beyond upstream; None when no upstream is set.
        behind: Upstream commits beyond local; None when no upstream is set.
        merging: True when merge/rebase/cherry-pick is in progress.
        conflict_paths: Paths of conflicted files (conflict-status prefix in
            `git status --porcelain`). Empty when none.
    """

    branch: str
    uncommitted_count: int
    ahead: int | None
    behind: int | None
    merging: bool
    conflict_paths: tuple[str, ...]


def _run_git(home: Path, *args: str) -> str | None:
    """Run a git subcommand inside lac home. Returns stdout or None on failure."""
    result = subprocess.run(["git", *args], cwd=home, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def lac_home_git_status(home: Path) -> LacHomeGitStatus | None:
    """Inspect lac home git state for the status display.

    Args:
        home: lac home directory.

    Returns:
        Snapshot on success. None when `home/.git` is missing or git is unavailable.
    """
    git_dir = home / ".git"
    if not git_dir.is_dir():
        return None

    branch_out = _run_git(home, "branch", "--show-current")
    porcelain_out = _run_git(home, "status", "--porcelain")
    if branch_out is None or porcelain_out is None:
        return None
    branch = branch_out.strip()

    uncommitted_count = 0
    conflict_paths: list[str] = []
    for line in porcelain_out.splitlines():
        if len(line) < 2:
            continue
        if line[:2] in CONFLICT_PREFIXES:
            conflict_paths.append(line[3:])  # porcelain v1: "XY <path>"
        else:
            uncommitted_count += 1

    ahead_out = _run_git(home, "rev-list", "--count", "@{u}..HEAD")
    behind_out = _run_git(home, "rev-list", "--count", "HEAD..@{u}")
    ahead = int(ahead_out.strip()) if ahead_out is not None else None
    behind = int(behind_out.strip()) if behind_out is not None else None

    merging = any(
        (git_dir / name).exists() for name in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")
    )

    return LacHomeGitStatus(
        branch=branch,
        uncommitted_count=uncommitted_count,
        ahead=ahead,
        behind=behind,
        merging=merging,
        conflict_paths=tuple(conflict_paths),
    )
