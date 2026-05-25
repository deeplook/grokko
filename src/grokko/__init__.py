"""Public package entrypoints for the `grokko` CLI."""

from __future__ import annotations

from typing import Any

__all__ = ["main"]


def main(*args: Any, **kwargs: Any) -> Any:
    """Run the CLI without importing it at package import time."""
    from grokko.cli import main as cli_main

    return cli_main(*args, **kwargs)
