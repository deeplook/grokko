"""Tests for _overview internals: depth limit, circular reference, edge cases."""

from __future__ import annotations

import click
import typer
from typer.testing import CliRunner

from grokko._overview import _print_commands, add_overview_command

runner = CliRunner()


def _make_group(name: str = "root", **cmds: click.Command) -> click.Group:
    g = click.Group(name=name)
    for cmd_name, cmd in cmds.items():
        g.add_command(cmd, name=cmd_name)
    return g


def _make_cmd(name: str, help: str = "") -> click.Command:
    @click.command(name=name, help=help)
    def _cmd() -> None:
        pass

    return _cmd


# ---------------------------------------------------------------------------
# _print_commands edge cases
# ---------------------------------------------------------------------------


def test_print_commands_no_commands(capsys: object) -> None:
    empty_group = click.Group(name="empty")
    app = typer.Typer()

    @app.command()
    def run() -> None:
        _print_commands(empty_group)

    result = runner.invoke(app, [])
    assert "(no commands registered)" in result.output


def test_print_commands_depth_limit(capsys: object) -> None:
    group = _make_group("root", hello=_make_cmd("hello"))
    app = typer.Typer()

    @app.command()
    def run() -> None:
        _print_commands(group, indent=1, max_depth=0)

    result = runner.invoke(app, [])
    assert "(max depth reached)" in result.output


def test_print_commands_circular_reference() -> None:
    group = _make_group("root", hello=_make_cmd("hello"))
    app = typer.Typer()

    @app.command()
    def run() -> None:
        _print_commands(group, seen={id(group)})

    result = runner.invoke(app, [])
    assert "(circular reference detected)" in result.output


def test_print_commands_no_params_command() -> None:
    @click.command(name="bare")
    def bare_cmd() -> None:
        pass

    # Strip all params (even --help) to hit the "no params" branch
    bare_cmd.params = []
    group = _make_group("root", bare=bare_cmd)
    app = typer.Typer()

    @app.command()
    def run() -> None:
        _print_commands(group)

    result = runner.invoke(app, [])
    assert "Parameters : (none)" in result.output


# ---------------------------------------------------------------------------
# add_overview_command integration
# ---------------------------------------------------------------------------


def test_overview_shows_nested_group() -> None:
    sub_app = typer.Typer(help="Sub group")

    @sub_app.command("do")
    def do_cmd() -> None:
        pass

    main_app = typer.Typer()
    main_app.add_typer(sub_app, name="sub")
    add_overview_command(main_app)

    result = runner.invoke(main_app, ["overview"])
    assert result.exit_code == 0
    assert "sub" in result.output
    assert "[group]" in result.output
