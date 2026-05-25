"""Tests for entry-point based CLI plugins."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import typer
from typer.testing import CliRunner

from grokko._overview import add_overview_command
from grokko._plugins import DEFAULT_ENTRY_POINT_GROUP, load_command_plugins

runner = CliRunner()


@dataclass
class FakeEntryPoint:
    """Minimal stand-in for an importlib metadata entry point."""

    name: str
    value: object
    error: Exception | None = None

    def load(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value


def test_loads_typer_app_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an entry point can add a nested Typer app."""
    app = typer.Typer()
    plugin_app = typer.Typer()

    @plugin_app.command("hello")
    def hello() -> None:
        typer.echo("hello from plugin")

    entry_point = FakeEntryPoint("premium", plugin_app)
    monkeypatch.setattr(
        "grokko._plugins.metadata.entry_points",
        lambda group=None: [entry_point] if group == DEFAULT_ENTRY_POINT_GROUP else [],
    )

    load_command_plugins(app)

    result = runner.invoke(app, ["premium", "hello"])
    assert result.exit_code == 0
    assert "hello from plugin" in result.output


def test_loads_command_callback_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an entry point can add a single Typer command."""
    app = typer.Typer()

    @app.command("base")
    def base() -> None:
        pass

    def plugin_command() -> None:
        typer.echo("plain plugin")

    entry_point = FakeEntryPoint("plain", plugin_command)
    monkeypatch.setattr(
        "grokko._plugins.metadata.entry_points",
        lambda group=None: [entry_point] if group == DEFAULT_ENTRY_POINT_GROUP else [],
    )

    load_command_plugins(app)

    result = runner.invoke(app, ["plain"])
    assert result.exit_code == 0
    assert "plain plugin" in result.output


def test_load_command_plugins_skips_duplicates_and_continues(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that duplicate and broken plugins are skipped without aborting."""
    app = typer.Typer()

    @app.command("core")
    def core() -> None:
        typer.echo("core command")

    def duplicate() -> None:
        typer.echo("duplicate plugin")

    def valid() -> None:
        typer.echo("valid plugin")

    entry_points = [
        FakeEntryPoint("core", duplicate),
        FakeEntryPoint("broken", None, RuntimeError("boom")),
        FakeEntryPoint("valid", valid),
    ]
    monkeypatch.setattr(
        "grokko._plugins.metadata.entry_points",
        lambda group=None: entry_points if group == DEFAULT_ENTRY_POINT_GROUP else [],
    )

    load_command_plugins(app)
    captured = capsys.readouterr()

    assert "skipping plugin 'core'" in captured.err
    assert "failed to load plugin 'broken'" in captured.err

    duplicate_result = runner.invoke(app, ["core"])
    assert duplicate_result.exit_code == 0
    assert "core command" in duplicate_result.output
    assert "duplicate plugin" not in duplicate_result.output

    valid_result = runner.invoke(app, ["valid"])
    assert valid_result.exit_code == 0
    assert "valid plugin" in valid_result.output


def test_plugin_appears_in_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that loaded plugins show up in the overview command."""
    app = typer.Typer()

    def plugin_command() -> None:
        typer.echo("plugin command")

    entry_point = FakeEntryPoint("premium", plugin_command)
    monkeypatch.setattr(
        "grokko._plugins.metadata.entry_points",
        lambda group=None: [entry_point] if group == DEFAULT_ENTRY_POINT_GROUP else [],
    )

    load_command_plugins(app)
    add_overview_command(app)

    result = runner.invoke(app, ["overview"])
    assert result.exit_code == 0
    assert "premium" in result.output


def test_plugins_appear_in_help_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that loaded plugins show up in the root help output."""
    app = typer.Typer()

    @app.command("base")
    def base() -> None:
        pass

    def plugin_command() -> None:
        typer.echo("plugin command")

    entry_point = FakeEntryPoint("premium", plugin_command)
    monkeypatch.setattr(
        "grokko._plugins.metadata.entry_points",
        lambda group=None: [entry_point] if group == DEFAULT_ENTRY_POINT_GROUP else [],
    )

    load_command_plugins(app)

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Plugins" in result.output
    assert "premium" in result.output


def test_register_plugin_raises_for_non_callable_non_typer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_register_plugin raises TypeError for invalid plugin objects."""
    from grokko._plugins import _register_plugin

    app = typer.Typer()
    with pytest.raises(TypeError, match="entry point must load"):
        _register_plugin(app, "bad", 42)


def test_iter_entry_points_fallback_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """_iter_entry_points falls back to .select() on TypeError."""
    from grokko._plugins import _iter_entry_points

    class FakeEPs:
        def select(self, group: str) -> list[object]:
            return ["ep_from_select"]

    def broken_entry_points(**kwargs: object) -> object:
        if kwargs:
            raise TypeError("no kwargs")
        return FakeEPs()

    monkeypatch.setattr("grokko._plugins.metadata.entry_points", broken_entry_points)
    result = _iter_entry_points("some.group")
    assert result == ["ep_from_select"]


def test_iter_entry_points_fallback_getitem(monkeypatch: pytest.MonkeyPatch) -> None:
    """_iter_entry_points falls back to dict.get() when .select() is unavailable."""
    from grokko._plugins import _iter_entry_points

    eps_dict = {"my.group": ["ep_from_dict"]}

    def broken_entry_points(**kwargs: object) -> object:
        if kwargs:
            raise TypeError("no kwargs")
        return eps_dict

    monkeypatch.setattr("grokko._plugins.metadata.entry_points", broken_entry_points)
    result = _iter_entry_points("my.group")
    assert result == ["ep_from_dict"]
