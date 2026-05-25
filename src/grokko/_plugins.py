"""Entry-point based Typer command plugin loader."""

from __future__ import annotations

from importlib import metadata
from typing import Any

import typer

DEFAULT_ENTRY_POINT_GROUP = "grokko.plugins"
PLUGIN_HELP_PANEL = "Plugins"


def load_command_plugins(
    app: typer.Typer, group: str = DEFAULT_ENTRY_POINT_GROUP
) -> None:
    """Discover and register optional command plugins on a Typer app."""
    registered_names = _registered_command_names(app)

    for entry_point in _iter_entry_points(group):
        command_name = entry_point.name
        if command_name in registered_names:
            typer.echo(
                f"warning: skipping plugin '{command_name}' from '{group}' "
                "because a command with that name already exists",
                err=True,
            )
            continue

        try:
            plugin = entry_point.load()
        except Exception as exc:  # pragma: no cover - defensive guard
            typer.echo(
                f"warning: failed to load plugin '{command_name}' "
                f"from '{group}': {exc}",
                err=True,
            )
            continue

        try:
            _register_plugin(app, command_name, plugin)
        except Exception as exc:  # pragma: no cover - defensive guard
            typer.echo(
                f"warning: failed to register plugin '{command_name}' "
                f"from '{group}': {exc}",
                err=True,
            )
            continue

        registered_names.add(command_name)


def _iter_entry_points(group: str) -> list[Any]:
    """Return the installed entry points for one group."""
    try:
        return list(metadata.entry_points(group=group))
    except TypeError:
        entry_points = metadata.entry_points()
        if hasattr(entry_points, "select"):
            return list(entry_points.select(group=group))
        return list(entry_points.get(group, []))


def _register_plugin(app: typer.Typer, name: str, plugin: Any) -> None:
    """Register one loaded plugin object on the Typer app."""
    if isinstance(plugin, typer.Typer):
        app.add_typer(plugin, name=name, rich_help_panel=PLUGIN_HELP_PANEL)
        return

    if callable(plugin):
        app.command(name=name, rich_help_panel=PLUGIN_HELP_PANEL)(plugin)
        return

    raise TypeError(
        "entry point must load a typer.Typer instance or a callable command"
    )


def _registered_command_names(app: typer.Typer) -> set[str]:
    """Collect the command names already registered on the app."""
    names: set[str] = set()

    for command_info in getattr(app, "registered_commands", []) or []:
        name = getattr(command_info, "name", None)
        if isinstance(name, str) and name:
            names.add(name)

    for group_info in getattr(app, "registered_groups", []) or []:
        name = getattr(group_info, "name", None)
        if isinstance(name, str) and name:
            names.add(name)

    return names
