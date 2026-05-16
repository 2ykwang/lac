"""Master template management."""

from pathlib import Path

AGENT_CONFIG_FILES: list[str] = [
    "CLAUDE.md",
    "AGENTS.md",
    ".claude",
    ".agents",
    ".cursorrules",
    ".mcp.json",
]

_DIR_ENTRIES = {".claude", ".agents"}


def is_empty_entry(path: Path) -> bool:
    """Return True if path is a 0-byte file or an empty directory.

    Args:
        path: Path to check.

    Returns:
        True for 0-byte files or directories without entries; False otherwise.
    """
    if path.is_dir():
        return not any(path.iterdir())

    return path.stat().st_size == 0


def ensure_template(home: Path) -> Path:
    """Create ``home/_template`` with stub files. Do not overwrite existing entries.

    Args:
        home: lac home directory.

    Returns:
        Path of the template directory.
    """
    template_dir = home / "_template"
    template_dir.mkdir(parents=True, exist_ok=True)

    for name in AGENT_CONFIG_FILES:
        entry = template_dir / name
        if entry.exists():
            continue

        if name in _DIR_ENTRIES:
            entry.mkdir(parents=True, exist_ok=True)
        elif name.endswith(".json"):
            entry.write_text("{}\n")
        else:
            entry.touch()

    return template_dir
