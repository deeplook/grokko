"""Integration tests for the plugin loader using real dist-info discovery."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from grokko._plugins import DEFAULT_ENTRY_POINT_GROUP, load_command_plugins

runner = CliRunner()


@pytest.fixture()
def real_plugin_on_path(tmp_path: Path) -> Generator[Path, None, None]:
    """Install a tiny dummy plugin via a real dist-info on sys.path."""
    (tmp_path / "grokko_dummy_plugin.py").write_text(
        "import typer\n"
        "app = typer.Typer()\n\n"
        "@app.command('greet')\n"
        "def greet() -> None:\n"
        "    typer.echo('hello from real plugin')\n"
    )

    dist_info = tmp_path / "grokko_dummy_plugin-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: grokko-dummy-plugin\nVersion: 1.0\n"
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{DEFAULT_ENTRY_POINT_GROUP}]\ndummy = grokko_dummy_plugin:app\n"
    )

    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    try:
        yield tmp_path
    finally:
        sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()
        sys.modules.pop("grokko_dummy_plugin", None)


def test_real_plugin_discovered_and_invokable(
    real_plugin_on_path: Path,
) -> None:
    """A plugin installed as a real dist-info entry point is discovered and works."""
    app = typer.Typer()
    load_command_plugins(app)

    result = runner.invoke(app, ["dummy", "greet"])
    assert result.exit_code == 0
    assert "hello from real plugin" in result.output


def test_real_plugin_appears_in_help(real_plugin_on_path: Path) -> None:
    """A real plugin shows up in the help panel."""
    app = typer.Typer()

    @app.command("base")
    def base() -> None:
        pass

    load_command_plugins(app)
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dummy" in result.output
    assert "Plugins" in result.output
