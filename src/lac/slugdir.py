"""Slug directory initialization."""

from datetime import UTC, datetime
from pathlib import Path

from .gitutil import git_remote_url
from .home import ensure_lac_home, get_lac_home
from .meta import Meta
from .slug import generate_slug, generate_slug_from_remote


def _fallback_slug(repo_path: Path, remote: str | None) -> str:
    """Return the fallback slug name for a repo, preferring remote when present."""
    if remote is not None:
        return generate_slug_from_remote(remote)

    return generate_slug(repo_path)


def get_slug_dir(repo_path: Path) -> Path:
    """Return the slug directory for `repo_path`.

    Lookup priority: `meta.repo_remote` (cross-machine identity) →
    `meta.repo_path` (single-machine identity, also covers renamed slugs).
    Falls back to a remote-based or path-hash slug name when no slug
    claims this repo.

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

        if meta.repo_path == target_path:
            return entry

    return fallback


def init_slug_dir(repo_path: Path) -> Path:
    """Create slug dir and write initial `.lac.meta`. Idempotent.

    Resolves the slug via `get_slug_dir` so a previously renamed slug is
    reused instead of creating a duplicate at the path-hash name.

    Args:
        repo_path: Repo working directory.

    Returns:
        Slug directory path. Created if missing.
    """
    ensure_lac_home()
    slug_dir = get_slug_dir(repo_path)

    if slug_dir.exists():
        return slug_dir

    slug_dir.mkdir(parents=True)
    Meta(
        repo_path=str(repo_path.resolve()),
        repo_remote=git_remote_url(repo_path),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    ).save(slug_dir / ".lac.meta")

    return slug_dir
