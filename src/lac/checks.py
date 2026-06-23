"""Integrity checks for lac home slugs.

Provides a Finding dataclass plus concrete checkers wired into `cli.py:doctor`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .gitutil import split_block
from .meta import Meta
from .template import is_empty_entry

Severity = Literal["info", "warn", "error"]


@dataclass(frozen=True)
class Finding:
    """A single integrity-check observation.

    Attributes:
        slug: Slug directory name. Empty string for lac-home-level findings.
        severity: One of "info", "warn", "error".
        code: Short stable identifier (e.g. "EXC001").
        message: One-line human-readable summary.
        hint: Suggested user action; None when no concrete suggestion.
    """

    slug: str
    severity: Severity
    code: str
    message: str
    hint: str | None = None


def check_symlink(repo_path: Path, slug_dir: Path, name: str) -> str | None:
    """Inspect a managed symlink for health.

    Args:
        repo_path: Repo working directory.
        slug_dir: Slug directory under lac home.
        name: Entry name relative to `repo_path` and `slug_dir`.

    Returns:
        None when the symlink is healthy, else a short failure reason.
    """
    link_path = repo_path / name
    target = slug_dir / name
    if not link_path.is_symlink():
        return "not a managed link"
    try:
        current = (link_path.parent / os.readlink(link_path)).resolve()
    except OSError:
        return "unreadable link"
    if current != target.resolve():
        return "wrong target"
    if not target.exists():
        return "target missing"
    return None


def check_symlink_targets(repo_path: Path, meta: Meta, slug_dir: Path) -> list[Finding]:
    """Report broken managed symlinks (`wrong target` / `unreadable` / `not a managed link`).

    Excludes `target missing`; that case is reported by `check_slug_missing_files`.

    Args:
        repo_path: Repo working directory.
        meta: Slug metadata.
        slug_dir: Slug directory under lac home.

    Returns:
        Findings, one per broken entry.
    """
    findings: list[Finding] = []
    for name in meta.linked_files:
        reason = check_symlink(repo_path, slug_dir, name)
        if reason and reason != "target missing":
            findings.append(
                Finding(
                    slug=slug_dir.name,
                    severity="error",
                    code="BRK001",
                    message=f"{name} ({reason})",
                )
            )
    return findings


def check_slug_missing_files(repo_path: Path, meta: Meta, slug_dir: Path) -> list[Finding]:
    """Report linked entries whose slug-side target is missing.

    Args:
        repo_path: Repo working directory.
        meta: Slug metadata.
        slug_dir: Slug directory under lac home.

    Returns:
        Findings, one per linked entry without a slug-side file.
    """
    findings: list[Finding] = []
    for name in meta.linked_files:
        if check_symlink(repo_path, slug_dir, name) == "target missing":
            findings.append(
                Finding(
                    slug=slug_dir.name,
                    severity="error",
                    code="MIS001",
                    message=name,
                )
            )
    return findings


def check_slug_extra_files(
    repo_path: Path,  # noqa: ARG001 — uniform checker call signature in doctor
    meta: Meta,
    slug_dir: Path,
) -> list[Finding]:
    """Report slug-side files not tracked in meta `linked_files`/`unlinked_files`.

    Skips lac's own files (`.lac.meta`, `.lac.local`) and empty-entry placeholders.

    Args:
        repo_path: Repo working directory (unused; kept for uniform checker call).
        meta: Slug metadata.
        slug_dir: Slug directory under lac home.

    Returns:
        Findings, one per untracked non-empty entry.
    """
    linked_set = set(meta.linked_files)
    kept_set = set(meta.unlinked_files)
    findings: list[Finding] = []
    for child in sorted(slug_dir.iterdir()):
        if child.name in (".lac.meta", ".lac.local"):
            continue
        if child.name in linked_set:
            continue
        if child.name in kept_set:
            continue
        if is_empty_entry(child):
            continue
        findings.append(
            Finding(
                slug=slug_dir.name,
                severity="error",
                code="EXT001",
                message=child.name,
            )
        )
    return findings


def check_exclude_block_integrity(repo_path: Path, meta: Meta, slug_dir: Path) -> list[Finding]:
    """Report drift between `meta.linked_files` and `.git/info/exclude` lac block.

    Args:
        repo_path: Repo working directory.
        meta: Slug metadata.
        slug_dir: Slug directory under lac home.

    Returns:
        Single drift finding when the block does not match `meta.linked_files`,
        else empty list. Compares as sets — order and duplicates within the lac
        block are not treated as drift.
    """
    exclude = repo_path / ".git" / "info" / "exclude"
    if exclude.exists():
        _, block, _ = split_block(exclude.read_text().splitlines())
    else:
        block = []
    if set(block) != set(meta.linked_files):
        return [
            Finding(
                slug=slug_dir.name,
                severity="warn",
                code="EXC001",
                message="exclude block drift",
                hint="unregister and re-link to reconcile",
            )
        ]
    return []
