"""Rich-styled console output helpers."""

from rich.console import Console

_console = Console()
_err_console = Console(stderr=True)


def ok(msg: str) -> None:
    """Print a success line in green.

    Args:
        msg: Message to print after the "ok" tag.
    """
    _console.print(f"[green]ok[/green]    {msg}")


def skip(msg: str, reason: str = "") -> None:
    """Print a skipped-action line in yellow with an optional reason.

    Args:
        msg: Message to print after the "skip" tag.
        reason: Parenthesized reason appended to the message; empty to omit.
    """
    suffix = f" ({reason})" if reason else ""
    _console.print(f"[yellow]skip[/yellow]  {msg}{suffix}")


def warn(msg: str) -> None:
    """Print a warning line in yellow.

    Args:
        msg: Message to print after the "warn" tag.
    """
    _console.print(f"[yellow]warn[/yellow]  {msg}")


def error(msg: str) -> None:
    """Print an error line in red to stderr.

    Args:
        msg: Message to print after the "error" tag.
    """
    _err_console.print(f"[red]error[/red] {msg}")


def info(msg: str) -> None:
    """Print an informational line in cyan.

    Args:
        msg: Message to print after the "info" tag.
    """
    _console.print(f"[cyan]info[/cyan]  {msg}")


def console() -> Console:
    """Return the shared Console instance (for advanced output like Table)."""
    return _console
