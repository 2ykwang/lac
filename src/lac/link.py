"""Symlink helpers."""

import os
from pathlib import Path


def make_symlink(target: Path, link: Path) -> None:
    """Create a symlink at `link` pointing to `target`.

    Idempotent when `link` already points to the same resolved `target`.

    Args:
        target: Path the symlink should point to.
        link: Path where the symlink is created.

    Raises:
        FileExistsError: `link` exists as a regular file/dir, or as a symlink
            pointing elsewhere.
    """
    target_abs = target.resolve()
    if link.is_symlink():
        current = Path(os.readlink(link))
        current_abs = current if current.is_absolute() else (link.parent / current)
        if current_abs.resolve() == target_abs:
            return

        raise FileExistsError(f"{link} is a symlink to {current}, not {target}")

    if link.exists():
        raise FileExistsError(f"{link} exists and is not a managed symlink")

    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target_abs, link)


def unlink_safely(link: Path, expected_target: Path | None = None) -> None:
    """Remove `link` only if it is a symlink (optionally matching `expected_target`).

    No-op if `link` does not exist.

    Args:
        link: Path of the symlink to remove.
        expected_target: If given, refuse removal unless the symlink resolves to it.

    Raises:
        FileExistsError: `link` is a regular file/dir, or points to an
            unexpected target when `expected_target` is given.
    """
    if not link.is_symlink():
        if link.exists():
            raise FileExistsError(f"{link} is not a symlink; refusing to remove")

        return

    if expected_target is not None:
        current = Path(os.readlink(link))
        current_abs = current if current.is_absolute() else (link.parent / current)
        if current_abs.resolve() != expected_target.resolve():
            raise FileExistsError(f"{link} points to {current}, expected {expected_target}")

    link.unlink()
