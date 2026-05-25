"""Pytest configuration — disable Rich/Typer ANSI output for all tests."""

from __future__ import annotations

import os

os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
