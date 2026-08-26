"""Command-line entrypoints for export and conversation flows."""

from __future__ import annotations

import json as _json
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from dotenv import find_dotenv, load_dotenv

load_dotenv(dotenv_path=find_dotenv(usecwd=True))


from grokko._http import GrokApiError  # noqa: E402
from grokko._overview import add_overview_command  # noqa: E402
from grokko._plugins import load_command_plugins  # noqa: E402
from grokko.attachments import collect_attachments, download_attachments  # noqa: E402
from grokko.config import GrokSessionConfig  # noqa: E402
from grokko.conversations import GrokConversationClient  # noqa: E402
from grokko.export import GrokExportManager  # noqa: E402
from grokko.extract import GrokExtractManager, parse_attachment_modes  # noqa: E402
from grokko.session import GrokSessionManager  # noqa: E402

# Create the main app
app = typer.Typer(
    name="grokko",
    help="CLI for capturing, requesting, and downloading Grok data exports",
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Create sub-apps for command groups
session_app = typer.Typer(
    help="Manage stored session cookies and login state",
    context_settings={"help_option_names": ["-h", "--help"]},
)
export_app = typer.Typer(
    help="Trigger, download, and inspect Grok account exports.",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(session_app, name="session")

try:
    __version__ = package_version("grokko")
except PackageNotFoundError:
    __version__ = "0.1.0"


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Show concise help when the root command is invoked without a subcommand."""
    if version:
        typer.echo(f"grokko {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_chat_index(value: str) -> tuple[int, int] | int:
    """Parse one chat index or a half-open slice expression like `3:10`."""
    if ":" not in value:
        index = int(value)
        if index < 0:
            raise ValueError("chat index must be non-negative")
        return index

    start_text, stop_text = value.split(":", 1)
    if not start_text or not stop_text:
        raise ValueError("chat index slice must have the form START:STOP")

    start = int(start_text)
    stop = int(stop_text)
    if start < 0 or stop < 0:
        raise ValueError("chat index slice must be non-negative")
    if stop < start:
        raise ValueError("chat index slice must satisfy START <= STOP")
    return (start, stop)


def _conversation_id(convo: dict[str, object]) -> str:
    """Extract the canonical conversation ID from one metadata payload."""
    return str(
        convo.get("conversationId")
        or convo.get("id")
        or convo.get("conversation_id", "")
    )


def _load_conversation_responses(
    client: GrokConversationClient, conversation_id: str
) -> list[dict[str, Any]]:
    """Load all response payloads for one conversation ID."""
    node = client.get_response_node(conversation_id)
    nodes = node.get("responseNodes") or node.get("response_nodes") or []
    if nodes:
        response_ids = [
            str(n["responseId"])
            for n in cast(list[dict[str, Any]], nodes)
            if "responseId" in n
        ]
    else:
        response_ids = cast(
            list[str], node.get("responseIds") or node.get("response_ids") or []
        )
    if not response_ids and isinstance(node, list):
        response_ids = cast(list[str], node)
    if not response_ids:
        return []
    return client.load_responses(conversation_id, response_ids)


def _print_convo_summary(convo: dict[str, Any] | None, convo_id: str) -> None:
    """Print a short human-readable summary for one conversation."""
    url = f"https://grok.com/c/{convo_id}" if convo_id else "(unknown)"
    if convo is None:
        typer.echo(f"URL:      {url}")
        return
    title = convo.get("title") or convo.get("name") or "(untitled)"
    created = (
        convo.get("createTime") or convo.get("createdAt") or convo.get("created_at", "")
    )
    modified = (
        convo.get("modifyTime")
        or convo.get("modifiedAt")
        or convo.get("updatedAt")
        or convo.get("modified_at", "")
    )
    typer.echo(f"Title:    {title}")
    typer.echo(f"URL:      {url}")
    if created:
        typer.echo(f"Created:  {created}")
    if modified:
        typer.echo(f"Modified: {modified}")


def _strip_web_results(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "webSearchResults"} for r in responses]


def _print_transcript(
    responses: list[dict[str, Any]],
    *,
    messages: bool = True,
    sources: bool = False,
) -> None:
    """Render a conversation transcript, optionally including cited sources."""
    for msg in responses:
        role = msg.get("sender") or msg.get("role") or "unknown"
        label = "User" if str(role).lower() in ("human", "user") else "Grok"
        if sources and label == "Grok":
            web = msg.get("webSearchResults") or []
            if web:
                if messages:
                    content = (
                        msg.get("message")
                        or msg.get("content")
                        or msg.get("text")
                        or ""
                    )
                    if isinstance(content, dict):
                        content = (
                            content.get("content")
                            or content.get("text")
                            or str(content)
                        )
                    typer.echo(f"{label}: {content.strip()}")
                typer.echo("  Sources:")
                for r in web:
                    title = r.get("title", "")
                    url = r.get("url", "")
                    typer.echo(f"    - {title}  {url}")
                typer.echo()
                continue
        if not messages:
            continue
        content = msg.get("message") or msg.get("content") or msg.get("text") or ""
        if isinstance(content, dict):
            content = content.get("content") or content.get("text") or str(content)
        typer.echo(f"{label}: {content.strip()}")
        typer.echo()


def _get_config() -> GrokSessionConfig:
    """Get the session config."""
    return GrokSessionConfig()


def _require_auth(config: GrokSessionConfig) -> dict[str, Any]:
    """Load auth state or exit with error."""
    if not config.state_file.exists():
        typer.echo("No auth.json found — run 'grokko session capture' first.", err=True)
        raise typer.Exit(1)
    try:
        return cast(
            dict[str, Any], _json.loads(config.state_file.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        typer.echo(f"error: could not read auth.json: {exc}", err=True)
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# Session commands
# ---------------------------------------------------------------------------


@session_app.command("capture")
def session_capture() -> None:
    """Capture Grok session cookies from your local Chrome profile."""
    config = _get_config()
    manager = GrokSessionManager(config)
    if not manager.capture_from_chrome_cookies():
        raise typer.Exit(1)


@session_app.command("inspect")
def session_inspect() -> None:
    """Print a report of the stored session cookies."""
    config = _get_config()
    manager = GrokSessionManager(config)
    manager.inspect()


@session_app.command("ping")
def session_ping(
    headless: Annotated[bool, typer.Option(help="Run browser headless")] = False,
) -> None:
    """Check whether the stored session is still logged in."""
    config = _get_config()
    manager = GrokSessionManager(config)
    try:
        if not manager.ping(headless=headless):
            raise typer.Exit(1)
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# Export commands
# ---------------------------------------------------------------------------


@export_app.command("run")
def export_run(
    headless: Annotated[bool, typer.Option(help="Run browser headless")] = False,
    verbose: Annotated[bool, typer.Option("-v", help="Verbose output")] = False,
    dest: Annotated[
        Path | None,
        typer.Option(help="Output file path (default: ~/.grokko/<filename>)"),
    ] = None,
    url_only: Annotated[
        bool, typer.Option(help="Print URL without downloading")
    ] = False,
    inspect: Annotated[
        bool, typer.Option(help="Print a summary of the downloaded ZIP after saving")
    ] = False,
) -> None:
    """Trigger a data export, poll email for the link, and download the ZIP.

    The ZIP is saved to ~/.grokko/<filename> unless --dest is provided.
    Override the storage directory with the GROKKO_STORAGE_DIR env var.
    """
    config = _get_config()
    manager = GrokSessionManager(config)
    export_manager = GrokExportManager(manager)

    if not config.state_file.exists():
        typer.echo("No session found — run 'grokko session capture' first.", err=True)
        raise typer.Exit(1)

    manager.log("Checking session ...")
    try:
        logged_in = manager.ping(headless=headless)
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    if not logged_in:
        typer.echo(
            "Session is not valid — run 'grokko session capture' to refresh it.",
            err=True,
        )
        raise typer.Exit(1)

    dest_path = dest.expanduser() if dest else None

    if url_only:
        now = datetime.now(timezone.utc)
        after = now.replace(hour=0, minute=0, second=0, microsecond=0)
        manager.log("Triggering data export ...")
        if not export_manager.request_data_export(headless=headless):
            raise typer.Exit(1)
        try:
            url = export_manager.poll_for_export_url(after, verbose=verbose)
        except OSError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from None
        if url:
            typer.echo(url)
            return
        raise typer.Exit(1)

    try:
        path = export_manager.export_and_download(
            dest=dest_path, headless=headless, verbose=verbose
        )
    except (OSError, RuntimeError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None

    if not path:
        raise typer.Exit(1)

    try:
        display_path = Path("~") / path.relative_to(Path.home())
    except ValueError:
        display_path = path

    if inspect:
        export_manager.inspect_zip(path)
    else:
        typer.echo("\nNext steps:")
        typer.echo(f"  Inspect:  grokko export inspect {display_path}")
        typer.echo(f"  Extract:  grokko extract {display_path} <output_dir>")
        return

    typer.echo("\nNext step:")
    typer.echo(f"  Extract:  grokko extract {display_path} <output_dir>")


@export_app.command("download")
def export_download(
    url: Annotated[str, typer.Option(help="Download URL")],
    dest: Annotated[Path | None, typer.Option(help="Output file path")] = None,
    headless: Annotated[bool, typer.Option(help="Run browser headless")] = False,
) -> None:
    """Download a ZIP from a known export URL."""
    config = _get_config()
    manager = GrokSessionManager(config)
    export_manager = GrokExportManager(manager)

    dest_path = dest.expanduser() if dest else None
    path = export_manager.download_export_file(url, dest=dest_path, headless=headless)

    if not path:
        raise typer.Exit(1)


@export_app.command("inspect")
def export_inspect(
    zip: Annotated[
        Path | None,
        typer.Argument(help="Path to ZIP file (default: newest in ~/.grokko/)"),
    ] = None,
) -> None:
    """Print a summary of a downloaded Grok export ZIP."""
    config = _get_config()
    manager = GrokSessionManager(config)
    export_manager = GrokExportManager(manager)

    zip_path = zip.expanduser() if zip else None
    if not zip_path:
        zips = sorted(
            config.storage_dir.glob("*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not zips:
            typer.echo(
                "No ZIP file found. Pass --zip <path> or download an export first.",
                err=True,
            )
            raise typer.Exit(1)
        zip_path = zips[0]

    if not export_manager.inspect_zip(zip_path):
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Chat command
# ---------------------------------------------------------------------------


@app.command("chat")
def chat(
    index: Annotated[
        str, typer.Option("-n", help="Zero-based index or slice START:STOP")
    ] = "0",
    id: Annotated[
        str | None, typer.Option(help="Fetch by conversation ID (part of URL)")
    ] = None,
    messages: Annotated[
        bool,
        typer.Option(
            help="Show the message transcript (webSearchResults excluded from JSON)"
        ),
    ] = False,
    sources: Annotated[
        bool,
        typer.Option(
            help="Show web sources; with --messages, keeps webSearchResults in JSON"
        ),
    ] = False,
    json: Annotated[bool, typer.Option(help="Output raw JSON")] = False,
    attachments: Annotated[
        bool, typer.Option(help="Download attachments (requires --id)")
    ] = False,
    attachments_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory for attachments (default: ~/.grokko/attachments/<id>/)",
        ),
    ] = None,
) -> None:
    """Get a single Grok conversation (chat history).

    Flag combinations control what is shown:

    \b
      --messages          transcript only (webSearchResults stripped from JSON)
      --sources           web sources only (JSON key: webSearchResults)
      --messages --sources  full transcript with sources (webSearchResults kept in JSON)
      --attachments       download uploaded files and generated images (requires --id)
    """
    config = _get_config()
    state = _require_auth(config)
    client = GrokConversationClient(state.get("cookies", []), config.user_agent)

    if attachments and not id:
        typer.echo("error: --attachments requires --id", err=True)
        raise typer.Exit(1)

    if id:
        try:
            convo_item = client.get_conversation_by_id(id)
        except GrokApiError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        convo_id = _conversation_id(convo_item)
        if not convo_id:
            typer.echo(
                "error: could not determine conversation ID from API response.",
                err=True,
            )
            raise typer.Exit(1)

        try:
            responses = (
                _load_conversation_responses(client, convo_id)
                if (messages or sources or attachments)
                else None
            )
        except GrokApiError as exc:
            typer.echo(f"error fetching messages: {exc}", err=True)
            raise typer.Exit(1) from None

        if attachments and responses is not None:
            out_dir = (
                attachments_dir.expanduser()
                if attachments_dir
                else config.storage_dir / "attachments" / convo_id
            )
            found = collect_attachments(responses)
            if not found:
                typer.echo("No attachments found in this conversation.")
            else:
                typer.echo(f"Downloading {len(found)} attachment(s) → {out_dir}/")
                ok = download_attachments(found, out_dir, config.state_file)
                typer.echo(f"Done — {ok}/{len(found)} downloaded.")
            if not messages and not sources and not json:
                return

        if json and responses is not None:
            if sources and not messages:
                payload_sources = [
                    r.get("webSearchResults") or []
                    for r in responses
                    if r.get("webSearchResults")
                ]
                typer.echo(_json.dumps({"webSearchResults": payload_sources}, indent=2))
            else:
                out_responses = responses if sources else _strip_web_results(responses)
                typer.echo(
                    _json.dumps(
                        {"conversation": convo_item, "responses": out_responses},
                        indent=2,
                    )
                )
        elif json:
            typer.echo(_json.dumps(convo_item, indent=2))
        elif responses is not None:
            _print_convo_summary(convo_item, convo_id)
            if responses:
                typer.echo()
                _print_transcript(responses, messages=messages, sources=sources)
            else:
                typer.echo("\n(no messages found)")
        else:
            _print_convo_summary(convo_item, convo_id)
        return

    try:
        index_spec = _parse_chat_index(index)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    if isinstance(index_spec, int):
        try:
            convo_at_index: dict[str, Any] | None = client.get_conversation_by_index(
                index_spec
            )
        except GrokApiError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        if convo_at_index is None:
            typer.echo(f"No conversation at index {index_spec}.", err=True)
            raise typer.Exit(1)

        convo_id = _conversation_id(convo_at_index)
        if not convo_id:
            typer.echo(
                "error: could not determine conversation ID from API response.",
                err=True,
            )
            raise typer.Exit(1)

        if messages or sources:
            try:
                responses = _load_conversation_responses(client, convo_id)
            except GrokApiError as exc:
                typer.echo(f"error fetching messages: {exc}", err=True)
                raise typer.Exit(1) from None

            if json:
                if sources and not messages:
                    payload_sources = [
                        r.get("webSearchResults") or []
                        for r in responses
                        if r.get("webSearchResults")
                    ]
                    typer.echo(
                        _json.dumps({"webSearchResults": payload_sources}, indent=2)
                    )
                else:
                    out_responses = (
                        responses if sources else _strip_web_results(responses)
                    )
                    typer.echo(
                        _json.dumps(
                            {
                                "conversation": convo_at_index,
                                "responses": out_responses,
                            },
                            indent=2,
                        )
                    )
            else:
                _print_convo_summary(convo_at_index, convo_id)
                if responses:
                    typer.echo()
                    _print_transcript(responses, messages=messages, sources=sources)
                else:
                    typer.echo("\n(no messages found)")
            return

        if json:
            typer.echo(_json.dumps(convo_at_index, indent=2))
        else:
            _print_convo_summary(convo_at_index, convo_id)
        return

    start, stop = index_spec
    try:
        conversations = client.list_conversation_range(start, stop)
    except (GrokApiError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    if not conversations:
        typer.echo(f"No conversations in range {start}:{stop}.", err=True)
        raise typer.Exit(1)

    if json:
        payload: list[dict[str, Any]] = []
        for convo in conversations:
            if messages or sources:
                convo_id = _conversation_id(convo)
                try:
                    responses = (
                        _load_conversation_responses(client, convo_id)
                        if convo_id
                        else []
                    )
                except GrokApiError as exc:
                    typer.echo(f"error fetching messages: {exc}", err=True)
                    raise typer.Exit(1) from None
                if sources and not messages:
                    payload.append(
                        {
                            "webSearchResults": [
                                r.get("webSearchResults") or []
                                for r in responses
                                if r.get("webSearchResults")
                            ]
                        }
                    )
                else:
                    out_responses = (
                        responses if sources else _strip_web_results(responses)
                    )
                    payload.append({"conversation": convo, "responses": out_responses})
            else:
                payload.append(convo)
        typer.echo(_json.dumps(payload, indent=2))
        return

    for offset, convo in enumerate(conversations):
        convo_index = start + offset
        convo_id = _conversation_id(convo)
        typer.echo(f"[{convo_index}]")
        _print_convo_summary(convo, convo_id)
        if messages or sources:
            try:
                responses = _load_conversation_responses(client, convo_id)
            except GrokApiError as exc:
                typer.echo(f"error fetching messages: {exc}", err=True)
                raise typer.Exit(1) from None
            if responses:
                typer.echo()
                _print_transcript(responses, messages=messages, sources=sources)
            else:
                typer.echo("\n(no messages found)")
        if offset != len(conversations) - 1:
            typer.echo()


app.add_typer(export_app, name="export")


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Text to search for")],
    limit: Annotated[int, typer.Option("-n", help="Maximum number of results")] = 20,
    json: Annotated[bool, typer.Option(help="Output raw JSON")] = False,
) -> None:
    """Search Grok conversation titles and messages, printing matching URLs."""
    config = _get_config()
    state = _require_auth(config)
    client = GrokConversationClient(state.get("cookies", []), config.user_agent)

    try:
        results = client.search_conversations(query, page_size=limit)
    except GrokApiError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    if not results:
        typer.echo(f"No conversations found matching {query!r}.", err=True)
        raise typer.Exit(1)

    if json:
        typer.echo(_json.dumps(results, indent=2))
        return

    for i, result in enumerate(results):
        convo = result["conversation"]
        convo_id = _conversation_id(convo)
        _print_convo_summary(convo, convo_id)
        if result.get("highlight"):
            typer.echo(f"Match:    {result['highlight']}")
        if i != len(results) - 1:
            typer.echo()


@app.command("extract")
def extract(
    ctx: typer.Context,
    zip: Annotated[
        Path | None, typer.Argument(help="Path to Grok export ZIP file")
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Argument(help="Directory to write Markdown notes")
    ] = None,
    newest: Annotated[
        int | None, typer.Option(help="Export only N newest conversations")
    ] = None,
    limit: Annotated[
        int | None, typer.Option(help="Maximum conversations to export")
    ] = None,
    starred: Annotated[
        bool, typer.Option(help="Only export starred conversations")
    ] = False,
    oldest_first: Annotated[bool, typer.Option(help="Sort chronologically")] = False,
    attachments: Annotated[
        str,
        typer.Option(
            help="Attachment modes: none, all, files, edited-images, generated-images"
        ),
    ] = "",
    attachments_dir: Annotated[
        str, typer.Option(help="Directory for extracted attachments")
    ] = "_attachments",
) -> None:
    """Convert a Grok export ZIP to Obsidian Markdown notes."""
    if zip is None and output_dir is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    if zip is None:
        typer.echo("error: missing argument 'ZIP'", err=True)
        raise typer.Exit(2)
    if output_dir is None:
        typer.echo("error: missing argument 'OUTPUT_DIR'", err=True)
        raise typer.Exit(2)

    zip_path = zip.expanduser()
    out_dir = output_dir.expanduser()

    if not zip_path.exists():
        typer.echo(f"Error: ZIP not found: {zip_path}", err=True)
        raise typer.Exit(1)

    try:
        attachment_modes = parse_attachment_modes(attachments)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    export_limit = newest if newest is not None else limit
    if newest is not None:
        typer.echo(
            f"[grokko extract] Test mode — exporting {newest} newest conversations."
        )

    manager = GrokExtractManager(zip_path)
    try:
        count = manager.export(
            out_dir,
            limit=export_limit,
            starred_only=starred,
            newest_first=not oldest_first,
            attachment_modes=attachment_modes,
            attachments_dir=Path(attachments_dir),
        )
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"[grokko extract] Done — {count} note(s) written to {out_dir}")


# ---------------------------------------------------------------------------
# Setup command
# ---------------------------------------------------------------------------


@app.command("setup")
def setup() -> None:
    """Install Playwright browser dependencies if necessary."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        typer.echo("Playwright Chromium is already installed.")
    except Exception:
        typer.echo("Installing Playwright Chromium ...")
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
        )
        if result.returncode != 0:
            typer.echo("error: playwright install failed", err=True)
            raise typer.Exit(1) from None
        typer.echo("Done.")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

# Load optional entry-point based command plugins before adding overview so
# they appear in help output and the generated command summary.
load_command_plugins(app)

# Add overview command after all commands are registered
add_overview_command(app)


def main() -> None:
    """Run the CLI."""
    import typer.core as _typer_core

    _order = ["setup", "session", "chat", "search", "export", "extract", "overview"]
    click_group = cast(_typer_core.TyperGroup, typer.main.get_command(app))
    _old = dict(click_group.commands)
    click_group.commands = {k: _old[k] for k in _order if k in _old}
    click_group.commands.update(
        {k: v for k, v in _old.items() if k not in click_group.commands}
    )
    click_group()
