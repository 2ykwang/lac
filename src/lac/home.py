"""lac home directory resolution."""

import os
import subprocess
import sys
from pathlib import Path

from . import console
from .template import ensure_template


def get_lac_home() -> Path:
    """Resolve lac home: $LAC_HOME > $XDG_DATA_HOME/lac > ~/.local/share/lac.

    Returns:
        Resolved lac home path. Does not create the directory.
    """
    if "LAC_HOME" in os.environ:
        return Path(os.environ["LAC_HOME"]).expanduser()

    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "lac"


def ensure_lac_home() -> Path:
    """Create lac home directory, git-init it, and ensure the template exists. Idempotent.

    Returns:
        Resolved lac home path.

    Raises:
        SystemExit: If the resolved path exists but is not a directory.
    """
    home = get_lac_home()
    if home.exists() and not home.is_dir():
        console.error(f"lac home path is a file, not a directory: {home}")
        sys.exit(1)

    home.mkdir(parents=True, exist_ok=True)
    if not (home / ".git").is_dir():
        subprocess.run(["git", "init", "-q"], cwd=home, check=True)
    ensure_template(home)
    return home
