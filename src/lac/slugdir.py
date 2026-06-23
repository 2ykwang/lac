"""Slug directory initialization."""

from datetime import UTC, datetime
from pathlib import Path

from .gitutil import git_remote_url, read_slug_pointer, write_slug_pointer
from .home import ensure_lac_home, get_lac_home
from .meta import Meta
from .slug import generate_slug, generate_slug_from_remote

LOCAL_FILENAME = ".lac.local"


def read_local_path(slug_dir: Path) -> Path | None:
    """Return this machine's repo path bound to `slug_dir`, or None.

    Read from `<slug>/.lac.local` (gitignored, never synced). Presence means
    the slug is active on this machine; absence means it was registered on
    another machine and arrived via sync. Counterpart to the `.git/lac`
    pointer (which maps repo→slug); this maps slug→repo.

    Args:
        slug_dir: Slug directory under lac home.

    Returns:
        Absolute repo path on success, None when absent or unreadable.
    """
    try:
        raw = (slug_dir / LOCAL_FILENAME).read_text().strip()
    except OSError:
        return None
    return Path(raw) if raw else None


def write_local_path(slug_dir: Path, repo_path: Path) -> None:
    """Bind `slug_dir` to this machine's `repo_path` via `<slug>/.lac.local`.

    Args:
        slug_dir: Slug directory under lac home.
        repo_path: Repo working directory to record.
    """
    (slug_dir / LOCAL_FILENAME).write_text(str(repo_path.resolve()) + "\n")


def _fallback_slug(repo_path: Path, remote: str | None) -> str:
    """Return the fallback slug name for a repo, preferring remote when present."""
    if remote is not None:
        return generate_slug_from_remote(remote)

    return generate_slug(repo_path)


def get_slug_dir(repo_path: Path) -> Path:
    """Return the slug directory for `repo_path`.

    Lookup priority: `.git/lac` pointer (machine-local binding, survives path
    moves) → `meta.repo_remote` (cross-machine identity) → `.lac.local`
    (machine-local path, covers pointer-less/worktree repos). Falls back to a
    remote-based or path-hash slug name when no slug claims this repo.

    Args:
        repo_path: Repo working directory.

    Returns:
        Slug directory path. Existence is not guaranteed.
    """
    home = get_lac_home()
    remote = git_remote_url(repo_path)
    fallback = home / _fallback_slug(repo_path, remote)
    if not home.exists():
        return fallback

    # The pointer lives under the repo's `.git` (machine-local, never synced),
    # so it was written by this machine for this repo — its target's meta is
    # trusted without re-checking ownership. The guard rejects path traversal
    # and reserved (`.`/`_`) names; a stale pointer (target gone) falls through.
    pointer = read_slug_pointer(repo_path)
    if pointer is not None and "/" not in pointer and not pointer.startswith((".", "_")):
        pointed = home / pointer
        if (pointed / ".lac.meta").exists():
            return pointed

    target_path = str(repo_path.resolve())
    for entry in home.iterdir():
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        if ".bak." in entry.name:
            continue

        meta_path = entry / ".lac.meta"
        if not meta_path.exists():
            continue

        meta = Meta.load_safe(meta_path)
        if meta is None:
            continue

        if remote is not None and meta.repo_remote == remote:
            return entry

        local = read_local_path(entry)
        if local is not None and str(local) == target_path:
            return entry

    return fallback


def init_slug_dir(repo_path: Path) -> Path:
    """Create slug dir and write initial `.lac.meta`. Idempotent.

    Resolves the slug via `get_slug_dir` so a previously renamed slug is
    reused instead of creating a duplicate at the path-hash name. Records this
    machine's binding in `.git/lac` (repo→slug) and `<slug>/.lac.local`
    (slug→repo); the synced `.lac.meta` holds no machine-local path.

    Args:
        repo_path: Repo working directory.

    Returns:
        Slug directory path. Created if missing.
    """
    ensure_lac_home()
    slug_dir = get_slug_dir(repo_path)

    if slug_dir.exists():
        meta_path = slug_dir / ".lac.meta"
        meta = Meta.load_safe(meta_path)
        # Re-save to strip any legacy machine-local `repo_path` key from the
        # synced meta. Corrupted meta is left for `doctor` to report.
        if meta is not None:
            meta.save(meta_path)
        write_slug_pointer(repo_path, slug_dir.name)
        write_local_path(slug_dir, repo_path)
        return slug_dir

    slug_dir.mkdir(parents=True)
    Meta(
        repo_remote=git_remote_url(repo_path),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    ).save(slug_dir / ".lac.meta")
    write_slug_pointer(repo_path, slug_dir.name)
    write_local_path(slug_dir, repo_path)

    return slug_dir
