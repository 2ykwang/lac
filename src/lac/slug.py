"""Repo slug generation."""

import hashlib
from pathlib import Path


def generate_slug(path: Path) -> str:
    """Generate stable slug from absolute path: ``{name}-{sha256[:6]}``.

    Args:
        path: Repo directory path. Resolved to absolute before hashing.

    Returns:
        Slug name of the form ``{basename}-{6 hex chars}``.
    """
    abs_path = str(path.resolve())
    digest = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:6]
    name = path.resolve().name or "root"
    return f"{name}-{digest}"


def generate_slug_from_remote(remote_url: str) -> str:
    """Generate stable slug from a normalized git remote URL.

    Args:
        remote_url: Normalized remote URL (e.g. ``github.com/user/repo``).

    Returns:
        Slug name ``{basename}-{6 hex chars}`` where basename is the last
        URL segment.
    """
    digest = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()[:6]
    basename = remote_url.rsplit("/", 1)[-1] or "root"
    return f"{basename}-{digest}"
