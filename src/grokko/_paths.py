"""Path display helpers shared across grokko."""

from __future__ import annotations

from pathlib import Path


def display_path(path: Path) -> str:
    """Render a path for display, collapsing the user's home directory to ``~``."""
    home = Path.home()
    if path == home:
        return "~"
    try:
        return str(Path("~") / path.relative_to(home))
    except ValueError:
        return str(path)
