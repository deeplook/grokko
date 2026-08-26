"""Tests for the typer-based CLI."""

from __future__ import annotations

import json
import zipfile
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import click
import pytest
import typer.main as typer_main
from click.testing import Result
from typer.testing import CliRunner

from grokko._http import GrokApiError
from grokko.cli import (
    _conversation_id,
    _parse_chat_index,
    app,
)
from grokko.session import GrokSessionManager

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared fixtures / helpers for chat command tests
# ---------------------------------------------------------------------------

FAKE_CONVO = {"conversationId": "abc123", "title": "Test Convo"}

FAKE_RESPONSES = [
    {"sender": "human", "message": "What is the weather?"},
    {
        "sender": "assistant",
        "message": "It is sunny.",
        "webSearchResults": [
            {"title": "Weather Today", "url": "https://weather.example.com"},
        ],
    },
    {"sender": "assistant", "message": "No sources for this one."},
]


def _make_chat_mocks(
    responses: list[Any] | None = None,
) -> tuple[Any, Any, Any]:
    """Return (auth_patch, client_patch, load_patch) context managers."""
    if responses is None:
        responses = FAKE_RESPONSES
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    load = patch("grokko.cli._load_conversation_responses", return_value=responses)
    return auth, client_cls, load


def _invoke_chat_with_id(*extra_args: str) -> Result:
    auth, client_cls, load = _make_chat_mocks()
    with auth, client_cls as MockClient, load:
        MockClient.return_value.get_conversation_by_id.return_value = FAKE_CONVO
        return runner.invoke(app, ["chat", "--id", "abc123", *extra_args])


def test_main_reorders_commands() -> None:
    """main() must present commands in the canonical order."""
    expected = ["setup", "session", "chat", "search", "export", "extract", "overview"]
    grp = cast(click.Group, typer_main.get_command(app))
    old = dict(grp.commands)
    grp.commands = {k: old[k] for k in expected if k in old}
    grp.commands.update({k: v for k, v in old.items() if k not in grp.commands})
    assert grp.list_commands(None) == expected  # type: ignore[arg-type]


def test_app_has_session_commands() -> None:
    """Test that session subcommands exist."""
    result = runner.invoke(app, ["session", "-h"])
    assert result.exit_code == 0
    assert "capture" in result.output
    assert "inspect" in result.output
    assert "ping" in result.output


def test_app_has_export_commands() -> None:
    """Test that export subcommands exist."""
    result = runner.invoke(app, ["export", "-h"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "download" in result.output
    assert "inspect" in result.output


def test_app_has_chat_command() -> None:
    """Test that chat command exists."""
    result = runner.invoke(app, ["chat", "-h"])
    assert result.exit_code == 0
    assert "--messages" in result.output
    assert "--sources" in result.output


def test_app_has_search_command() -> None:
    """Test that search command exists."""
    result = runner.invoke(app, ["search", "-h"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_search_prints_results_with_highlight() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.search_conversations.return_value = [
            {
                "conversation": FAKE_CONVO,
                "highlight": "matched snippet",
                "matchType": "MATCH_MESSAGE",
            }
        ]
        result = runner.invoke(app, ["search", "weather"])
    assert result.exit_code == 0
    assert "Test Convo" in result.output
    assert "https://grok.com/c/abc123" in result.output
    assert "matched snippet" in result.output
    MockClient.return_value.search_conversations.assert_called_once_with(
        "weather", page_size=20
    )


def test_search_json_output() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    payload = [{"conversation": FAKE_CONVO, "highlight": None, "matchType": None}]
    with auth, client_cls as MockClient:
        MockClient.return_value.search_conversations.return_value = payload
        result = runner.invoke(app, ["search", "weather", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == payload


def test_search_no_results_exits_nonzero() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.search_conversations.return_value = []
        result = runner.invoke(app, ["search", "nope"])
    assert result.exit_code == 1
    assert "No conversations found" in result.output


def test_search_api_error_exits_nonzero() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.search_conversations.side_effect = GrokApiError("boom")
        result = runner.invoke(app, ["search", "weather"])
    assert result.exit_code == 1
    assert "boom" in result.output


def test_app_has_extract_command() -> None:
    """Test that extract command exists."""
    result = runner.invoke(app, ["extract", "-h"])
    assert result.exit_code == 0
    assert "--starred" in result.output
    assert "--attachments" in result.output


def test_app_has_overview_command() -> None:
    """Test that overview command exists and works."""
    result = runner.invoke(app, ["overview"])
    assert result.exit_code == 0
    assert "Application Overview" in result.output
    assert "Commands" in result.output


def test_root_no_args_shows_help() -> None:
    """Test that running the app without a command shows help."""
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Commands" in result.output


def test_root_exposes_version_flag() -> None:
    """Test that the top-level CLI exposes a version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"grokko {package_version('grokko')}" in result.output


def test_overview_shows_all_commands() -> None:
    """Test that overview lists all top-level commands."""
    result = runner.invoke(app, ["overview"])
    assert result.exit_code == 0
    assert "chat" in result.output
    assert "export" in result.output
    assert "extract" in result.output
    assert "session" in result.output


def test_chat_index_parsing() -> None:
    """Test that chat index/slice syntax is accepted."""
    # Test single index
    result = runner.invoke(app, ["chat", "-h"])
    assert result.exit_code == 0
    assert "START:STOP" in result.output or "index" in result.output.lower()


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["-h"], ["chat", "export", "extract", "session"]),
        (["--help"], ["chat", "export", "extract", "session"]),
        (["session", "-h"], ["capture", "inspect", "ping"]),
        (["session", "--help"], ["capture", "inspect", "ping"]),
    ],
)
def test_help_aliases_work(args: list[str], expected: list[str]) -> None:
    """Test that both -h and --help are accepted."""
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    for item in expected:
        assert item in result.output


def test_extract_no_args_shows_help() -> None:
    """Test that extract shows help when called without arguments."""
    result = runner.invoke(app, ["extract"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "ZIP" in result.output
    assert "OUTPUT_DIR" in result.output


def test_gen_image_is_not_built_in() -> None:
    """Test that gen-image is no longer part of the built-in app."""
    result = runner.invoke(app, ["gen-image"])
    assert result.exit_code != 0
    assert "No such command" in result.output or "Usage" in result.output


def test_gen_video_is_not_built_in() -> None:
    """Test that gen-video is no longer part of the built-in app."""
    result = runner.invoke(app, ["gen-video"])
    assert result.exit_code != 0
    assert "No such command" in result.output or "Usage" in result.output


def test_session_capture_mock() -> None:
    """Test session capture with mocked manager."""
    with patch("grokko.cli.GrokSessionManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.capture_from_chrome_cookies.return_value = True
        result = runner.invoke(app, ["session", "capture"])
        assert result.exit_code == 0


def test_session_inspect_mock() -> None:
    """Test session inspect with mocked manager."""
    with patch("grokko.cli.GrokSessionManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.inspect.return_value = None
        result = runner.invoke(app, ["session", "inspect"])
        assert result.exit_code == 0


def test_session_ping_mock() -> None:
    """Test session ping with mocked manager."""
    with patch("grokko.cli.GrokSessionManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.ping.return_value = True
        result = runner.invoke(app, ["session", "ping"])
        assert result.exit_code == 0


def test_session_log_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that status logging goes to stderr instead of stdout."""
    manager = GrokSessionManager()
    manager.log("status message")
    captured = capsys.readouterr()
    assert "[grokko] status message" in captured.err
    assert "[grokko] status message" not in captured.out


# ---------------------------------------------------------------------------
# chat --sources / --messages flag behaviour
# ---------------------------------------------------------------------------


def test_chat_sources_only_hides_messages() -> None:
    """--sources alone must not print message text."""
    result = _invoke_chat_with_id("--sources")
    assert result.exit_code == 0
    assert "What is the weather?" not in result.output
    assert "It is sunny." not in result.output
    assert "No sources for this one." not in result.output


def test_chat_sources_only_shows_sources() -> None:
    """--sources alone must print web search source URLs."""
    result = _invoke_chat_with_id("--sources")
    assert result.exit_code == 0
    assert "weather.example.com" in result.output
    assert "Weather Today" in result.output


def test_chat_messages_only_shows_messages() -> None:
    """--messages alone must print message text."""
    result = _invoke_chat_with_id("--messages")
    assert result.exit_code == 0
    assert "What is the weather?" in result.output
    assert "It is sunny." in result.output


def test_chat_messages_only_hides_sources() -> None:
    """--messages alone must not print source URLs."""
    result = _invoke_chat_with_id("--messages")
    assert result.exit_code == 0
    assert "weather.example.com" not in result.output


def test_chat_messages_and_sources_shows_both() -> None:
    """--messages --sources must print both message text and source URLs."""
    result = _invoke_chat_with_id("--messages", "--sources")
    assert result.exit_code == 0
    assert "It is sunny." in result.output
    assert "weather.example.com" in result.output


# ---------------------------------------------------------------------------
# chat --json flag behaviour with --sources / --messages
# ---------------------------------------------------------------------------


def test_chat_json_sources_only_key() -> None:
    """--sources --json must output a top-level 'webSearchResults' key."""
    result = _invoke_chat_with_id("--sources", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "webSearchResults" in data
    assert "responses" not in data
    assert "conversation" not in data


def test_chat_json_sources_only_no_message_content() -> None:
    """--sources --json must not include message text in output."""
    result = _invoke_chat_with_id("--sources", "--json")
    assert result.exit_code == 0
    assert "What is the weather?" not in result.output
    assert "It is sunny." not in result.output


def test_chat_json_messages_strips_web_search_results() -> None:
    """--messages --json must omit webSearchResults from each response."""
    result = _invoke_chat_with_id("--messages", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "responses" in data
    for resp in data["responses"]:
        assert "webSearchResults" not in resp


def test_chat_json_messages_and_sources_keeps_web_search_results() -> None:
    """--messages --sources --json must keep webSearchResults in responses."""
    result = _invoke_chat_with_id("--messages", "--sources", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "responses" in data
    assert any("webSearchResults" in r for r in data["responses"])


# ---------------------------------------------------------------------------
# export inspect positional argument
# ---------------------------------------------------------------------------


def test_export_inspect_zip_is_positional() -> None:
    """export inspect must accept ZIP as a positional argument, not --zip."""
    result = runner.invoke(app, ["export", "inspect", "-h"])
    assert result.exit_code == 0
    assert "--zip" not in result.output
    assert "ZIP" in result.output


# ---------------------------------------------------------------------------
# export run --inspect flag and default path documentation
# ---------------------------------------------------------------------------


def test_export_run_has_inspect_flag() -> None:
    """export run must expose an --inspect flag."""
    result = runner.invoke(app, ["export", "run", "-h"])
    assert result.exit_code == 0
    assert "--inspect" in result.output


def test_export_run_help_mentions_default_path() -> None:
    """export run help must mention the default storage path."""
    result = runner.invoke(app, ["export", "run", "-h"])
    assert result.exit_code == 0
    assert "~/.grokko" in result.output


# ---------------------------------------------------------------------------
# _parse_chat_index helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0),
        ("5", 5),
        ("3:10", (3, 10)),
        ("0:0", (0, 0)),
    ],
)
def test_parse_chat_index_valid(value: str, expected: object) -> None:
    assert _parse_chat_index(value) == expected


@pytest.mark.parametrize(
    "value",
    ["-1", "3:1", "-1:5", "3:-1", ":5", "3:"],
)
def test_parse_chat_index_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_chat_index(value)


# ---------------------------------------------------------------------------
# _conversation_id helper
# ---------------------------------------------------------------------------


def test_conversation_id_uses_conversationId() -> None:
    assert _conversation_id({"conversationId": "abc"}) == "abc"


def test_conversation_id_falls_back_to_id() -> None:
    assert _conversation_id({"id": "xyz"}) == "xyz"


def test_conversation_id_falls_back_to_conversation_id() -> None:
    assert _conversation_id({"conversation_id": "zzz"}) == "zzz"


def test_conversation_id_empty_when_missing() -> None:
    assert _conversation_id({}) == ""


# ---------------------------------------------------------------------------
# chat by index (no --id)
# ---------------------------------------------------------------------------


def _invoke_chat_by_index(
    *extra_args: str, convo: dict[str, Any] | None = None
) -> Result:
    if convo is None:
        convo = FAKE_CONVO
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    load = patch("grokko.cli._load_conversation_responses", return_value=FAKE_RESPONSES)
    with auth, client_cls as MockClient, load:
        MockClient.return_value.get_conversation_by_index.return_value = convo
        return runner.invoke(app, ["chat", "-n", "0", *extra_args])


def test_chat_by_index_summary() -> None:
    result = _invoke_chat_by_index()
    assert result.exit_code == 0
    assert "Test Convo" in result.output


def test_chat_by_index_not_found() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.get_conversation_by_index.return_value = None
        result = runner.invoke(app, ["chat", "-n", "99"])
    assert result.exit_code == 1


def test_chat_by_index_with_messages() -> None:
    result = _invoke_chat_by_index("--messages")
    assert result.exit_code == 0
    assert "What is the weather?" in result.output


def test_chat_by_index_json() -> None:
    result = _invoke_chat_by_index("--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "conversationId" in data


def test_chat_by_index_messages_json() -> None:
    result = _invoke_chat_by_index("--messages", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "conversation" in data
    assert "responses" in data


def test_chat_by_index_api_error() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.get_conversation_by_index.side_effect = GrokApiError(
            "boom"
        )
        result = runner.invoke(app, ["chat", "-n", "0"])
    assert result.exit_code == 1


def test_chat_bad_index_exits_with_error() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    with auth, patch("grokko.cli.GrokConversationClient"):
        result = runner.invoke(app, ["chat", "-n", "-1"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# chat by slice
# ---------------------------------------------------------------------------


def _invoke_chat_slice(*extra_args: str) -> Result:
    convos = [
        {"conversationId": "a1", "title": "Alpha"},
        {"conversationId": "b2", "title": "Beta"},
    ]
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    load = patch("grokko.cli._load_conversation_responses", return_value=FAKE_RESPONSES)
    with auth, client_cls as MockClient, load:
        MockClient.return_value.list_conversation_range.return_value = convos
        return runner.invoke(app, ["chat", "-n", "0:2", *extra_args])


def test_chat_slice_summary() -> None:
    result = _invoke_chat_slice()
    assert result.exit_code == 0
    assert "Alpha" in result.output
    assert "Beta" in result.output


def test_chat_slice_json() -> None:
    result = _invoke_chat_slice("--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2


def test_chat_slice_messages_json() -> None:
    result = _invoke_chat_slice("--messages", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert all("responses" in item for item in data)


def test_chat_slice_sources_json() -> None:
    result = _invoke_chat_slice("--sources", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert all("webSearchResults" in item for item in data)


def test_chat_slice_empty_range() -> None:
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls as MockClient:
        MockClient.return_value.list_conversation_range.return_value = []
        result = runner.invoke(app, ["chat", "-n", "0:2"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# extract CLI command
# ---------------------------------------------------------------------------


def _make_export_zip(tmp_path: Path, n: int = 1) -> Path:
    zip_path = tmp_path / "export.zip"
    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": f"c{i}",
                    "title": f"Chat {i}",
                    "create_time": f"2026-01-{i + 10:02d}T10:00:00Z",
                },
                "responses": [],
            }
            for i in range(n)
        ]
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))
    return zip_path


def test_extract_missing_zip_arg(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["extract", str(out)])
    assert result.exit_code == 2


def test_extract_zip_not_found(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["extract", str(tmp_path / "missing.zip"), str(out)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "not found" in (result.stderr or "")


def test_extract_invalid_attachment_mode(tmp_path: Path) -> None:
    zip_path = _make_export_zip(tmp_path)
    out = tmp_path / "out"
    result = runner.invoke(
        app, ["extract", str(zip_path), str(out), "--attachments", "bogus"]
    )
    assert result.exit_code == 1


def test_extract_success(tmp_path: Path) -> None:
    zip_path = _make_export_zip(tmp_path, n=2)
    out = tmp_path / "out"
    result = runner.invoke(app, ["extract", str(zip_path), str(out)])
    assert result.exit_code == 0
    assert "2 note(s)" in result.output


def test_extract_newest_flag(tmp_path: Path) -> None:
    zip_path = _make_export_zip(tmp_path, n=3)
    out = tmp_path / "out"
    result = runner.invoke(app, ["extract", str(zip_path), str(out), "--newest", "1"])
    assert result.exit_code == 0
    assert "Test mode" in result.output
    assert "1 note(s)" in result.output


# ---------------------------------------------------------------------------
# chat --attachments flag
# ---------------------------------------------------------------------------

RESPONSES_WITH_ATTACHMENTS = [
    {
        "sender": "human",
        "message": "Look at this.",
        "fileAttachmentsMetadata": [
            {
                "fileMimeType": "image/png",
                "fileName": "logo.png",
                "fileUri": "users/u1/file-1/content",
            }
        ],
        "cardAttachmentsJson": [],
    },
    {
        "sender": "ASSISTANT",
        "message": "Done.",
        "fileAttachmentsMetadata": [],
        "cardAttachmentsJson": [
            json.dumps(
                {
                    "id": "card1",
                    "image_chunk": {
                        "imageUuid": "img-1",
                        "imageUrl": "users/u1/generated/img-1/image.jpg",
                        "seq": 1,
                        "progress": 100,
                    },
                }
            )
        ],
    },
]


def _invoke_chat_attachments(
    *extra_args: str,
    responses: list[Any] | None = None,
) -> tuple[Result, MagicMock]:
    """Invoke chat --id --attachments with download_attachments mocked out."""
    if responses is None:
        responses = RESPONSES_WITH_ATTACHMENTS
    auth, client_cls, load = _make_chat_mocks(responses)
    with auth, client_cls as MockClient, load:
        MockClient.return_value.get_conversation_by_id.return_value = FAKE_CONVO
        with patch("grokko.cli.download_attachments", return_value=2) as mock_dl:
            result = runner.invoke(
                app, ["chat", "--id", "abc123", "--attachments", *extra_args]
            )
            return result, mock_dl


def test_chat_attachments_requires_id() -> None:
    """--attachments without --id must exit with an error."""
    auth = patch("grokko.cli._require_auth", return_value={"cookies": []})
    client_cls = patch("grokko.cli.GrokConversationClient")
    with auth, client_cls:
        result = runner.invoke(app, ["chat", "--attachments"])
    assert result.exit_code != 0
    assert "--id" in result.output or "--id" in (result.stderr or "")


def test_chat_attachments_calls_download(tmp_path: Path) -> None:
    """--attachments must call download_attachments with found attachments."""
    result, mock_dl = _invoke_chat_attachments(
        "--attachments-dir", str(tmp_path / "out")
    )
    assert result.exit_code == 0
    mock_dl.assert_called_once()
    atts_arg = mock_dl.call_args[0][0]
    assert len(atts_arg) == 2
    filenames = {a.filename for a in atts_arg}
    assert "logo.png" in filenames
    assert "img-1.jpg" in filenames


def test_chat_attachments_default_output_dir() -> None:
    """Without --attachments-dir the output dir contains the conversation id."""
    result, mock_dl = _invoke_chat_attachments()
    assert result.exit_code == 0
    out_dir: Path = mock_dl.call_args[0][1]
    assert "abc123" in str(out_dir)


def test_chat_attachments_custom_output_dir(tmp_path: Path) -> None:
    """--attachments-dir overrides the default save location."""
    custom = tmp_path / "custom"
    result, mock_dl = _invoke_chat_attachments("--attachments-dir", str(custom))
    assert result.exit_code == 0
    assert mock_dl.call_args[0][1] == custom


def test_chat_attachments_reports_count() -> None:
    """Output must report how many files were downloaded."""
    result, _ = _invoke_chat_attachments()
    assert result.exit_code == 0
    assert "2/" in result.output


def test_chat_attachments_no_transcript_by_default() -> None:
    """--attachments alone must not print the message transcript."""
    result, _ = _invoke_chat_attachments()
    assert result.exit_code == 0
    assert "Look at this." not in result.output
    assert "Done." not in result.output


def test_chat_attachments_with_messages_shows_transcript() -> None:
    """--attachments --messages must download and also print the transcript."""
    result, mock_dl = _invoke_chat_attachments("--messages")
    assert result.exit_code == 0
    mock_dl.assert_called_once()
    assert "Look at this." in result.output


def test_chat_attachments_none_found() -> None:
    """When no attachments exist the command must report that and succeed."""
    auth, client_cls, load = _make_chat_mocks([{"sender": "human", "message": "hi"}])
    with auth, client_cls as MockClient, load:
        MockClient.return_value.get_conversation_by_id.return_value = FAKE_CONVO
        with patch("grokko.cli.download_attachments") as mock_dl:
            result = runner.invoke(app, ["chat", "--id", "abc123", "--attachments"])
    assert result.exit_code == 0
    assert "No attachments" in result.output
    mock_dl.assert_not_called()
