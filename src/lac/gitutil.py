"""Git interaction helpers."""

import subprocess
from pathlib import Path

LAC_MARK_START = "# === lac:start ==="
LAC_MARK_END = "# === lac:end ==="


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


def _exclude_path(repo: Path) -> Path:
    """Return the path of the `.git/info/exclude` file for `repo`."""
    return repo / ".git" / "info" / "exclude"


def _split_block(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split lines into (before_block, block_entries, after_block).

    Args:
        lines: Lines of `.git/info/exclude`.

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
    before, block, after = _split_block(existing)

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
    before, block, after = _split_block(existing)
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
