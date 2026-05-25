"""Pytest configuration — disable Rich/Typer colors for all tests."""

from __future__ import annotations

import os

os.environ.setdefault("NO_COLOR", "1")
