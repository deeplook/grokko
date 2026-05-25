"""Tests for the extract module (ZIP to Obsidian Markdown conversion)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from grokko.extract import (
    GrokExtractManager,
    _clean_message_text,
    _collect_generated_image_urls,
    _collect_image_edit_uris,
    _collect_media_types,
    _collect_queries,
    _collect_share_links,
    _collect_web_resources,
    _collect_webpage_urls,
    _collect_xpost_urls,
    _extract_attachments,
    _fmt_dt,
    _guess_extension,
    _is_image_ext,
    _note_filename,
    _parse_iso,
    _parse_response_time,
    _slugify,
    load_conversations,
    parse_attachment_modes,
)


def test_slugify_basic() -> None:
    assert _slugify("Hello World") == "Hello-World"
    assert _slugify("Test/File:Name") == "TestFileName"
    assert _slugify("  spaces  ") == "spaces"


def test_slugify_max_length() -> None:
    long_title = "A" * 100
    slug = _slugify(long_title, max_len=20)
    assert len(slug) == 20
    assert slug == "A" * 20


def test_note_filename() -> None:
    conv = {"title": "Test Conversation", "create_time": "2026-01-15T10:30:00Z"}
    filename = _note_filename(conv)
    assert filename == "2026-01-15 Test-Conversation.md"


def test_note_filename_missing_title() -> None:
    conv = {"create_time": "2026-01-15T10:30:00Z"}
    filename = _note_filename(conv)
    assert filename == "2026-01-15 untitled.md"


def test_note_filename_missing_date() -> None:
    conv = {"title": "Test"}
    filename = _note_filename(conv)
    assert filename == "0000-00-00 Test.md"


def test_parse_attachment_modes_empty() -> None:
    assert parse_attachment_modes("") == set()


def test_parse_attachment_modes_none() -> None:
    assert parse_attachment_modes("none") == set()


def test_parse_attachment_modes_all() -> None:
    assert parse_attachment_modes("all") == {
        "files",
        "edited-images",
        "generated-images",
    }


def test_parse_attachment_modes_specific() -> None:
    assert parse_attachment_modes("files") == {"files"}
    assert parse_attachment_modes("files,generated-images") == {
        "files",
        "generated-images",
    }


def test_parse_attachment_modes_invalid() -> None:
    with pytest.raises(ValueError):
        parse_attachment_modes("invalid")


def test_extract_manager_creates_output_dir(tmp_path: Path) -> None:
    """Test that extract creates the output directory if it doesn't exist."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    # Create minimal export ZIP
    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": "test-123",
                    "title": "Test Chat",
                    "create_time": "2026-01-15T10:30:00Z",
                },
                "responses": [
                    {
                        "response": {
                            "_id": "resp-1",
                            "sender": "human",
                            "message": "Hello",
                            "create_time": "2026-01-15T10:30:00Z",
                        }
                    }
                ],
            }
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    count = manager.export(output_dir)

    assert count == 1
    assert output_dir.exists()
    assert list(output_dir.glob("*.md"))[0].name == "2026-01-15 Test-Chat.md"


def test_extract_manager_limit(tmp_path: Path) -> None:
    """Test that --limit restricts the number of exported conversations."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": f"test-{i}",
                    "title": f"Chat {i}",
                    "create_time": f"2026-01-{i + 10:02d}T10:30:00Z",
                },
                "responses": [],
            }
            for i in range(5)
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    count = manager.export(output_dir, limit=2)

    assert count == 2
    assert len(list(output_dir.glob("*.md"))) == 2


def test_extract_manager_starred_only(tmp_path: Path) -> None:
    """Test that --starred filters to starred conversations only."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": "starred-1",
                    "title": "Starred Chat",
                    "create_time": "2026-01-15T10:30:00Z",
                    "starred": True,
                },
                "responses": [],
            },
            {
                "conversation": {
                    "id": "unstarred-1",
                    "title": "Regular Chat",
                    "create_time": "2026-01-16T10:30:00Z",
                    "starred": False,
                },
                "responses": [],
            },
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    count = manager.export(output_dir, starred_only=True)

    assert count == 1
    notes = list(output_dir.glob("*.md"))
    assert len(notes) == 1
    assert "Starred" in notes[0].name


def test_extract_manager_oldest_first(tmp_path: Path) -> None:
    """Test that --oldest-first reverses sort order."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": "newer",
                    "title": "Newer Chat",
                    "create_time": "2026-01-20T10:30:00Z",
                },
                "responses": [],
            },
            {
                "conversation": {
                    "id": "older",
                    "title": "Older Chat",
                    "create_time": "2026-01-10T10:30:00Z",
                },
                "responses": [],
            },
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    count = manager.export(output_dir, newest_first=False)

    assert count == 2
    notes = sorted(output_dir.glob("*.md"), key=lambda p: p.name)
    assert "Older" in notes[0].name
    assert "Newer" in notes[1].name


def test_extract_produces_valid_markdown(tmp_path: Path) -> None:
    """Test that exported Markdown has expected structure."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": "test-123",
                    "title": "Test Chat",
                    "create_time": "2026-01-15T10:30:00Z",
                    "modify_time": "2026-01-15T11:00:00Z",
                },
                "responses": [
                    {
                        "response": {
                            "_id": "resp-1",
                            "sender": "human",
                            "message": "What is 2+2?",
                            "create_time": "2026-01-15T10:30:00Z",
                            "model": "grok-3",
                        }
                    },
                    {
                        "response": {
                            "_id": "resp-2",
                            "sender": "assistant",
                            "message": "2+2 equals 4.",
                            "create_time": "2026-01-15T10:31:00Z",
                            "model": "grok-3",
                        }
                    },
                ],
            }
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    manager.export(output_dir)

    note_path = list(output_dir.glob("*.md"))[0]
    content = note_path.read_text()

    # Check YAML frontmatter
    assert "---" in content
    assert 'title: "Test Chat"' in content
    assert "conversation_id: test-123" in content
    assert "models:" in content
    assert "tags:" in content
    assert "- grok" in content

    # Check Markdown content
    assert "# Test Chat" in content
    assert "**User**" in content
    assert "**Grok**" in content
    assert "What is 2+2?" in content
    assert "2+2 equals 4." in content


def test_extract_handles_filename_collisions(tmp_path: Path) -> None:
    """Test that duplicate filenames are resolved with (1), (2) suffixes."""
    zip_path = tmp_path / "export.zip"
    output_dir = tmp_path / "notes"

    # Two conversations with same title and date
    payload = {
        "conversations": [
            {
                "conversation": {
                    "id": "dup-1",
                    "title": "Duplicate",
                    "create_time": "2026-01-15T10:30:00Z",
                },
                "responses": [],
            },
            {
                "conversation": {
                    "id": "dup-2",
                    "title": "Duplicate",
                    "create_time": "2026-01-15T10:30:00Z",
                },
                "responses": [],
            },
        ]
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))

    manager = GrokExtractManager(zip_path)
    count = manager.export(output_dir)

    assert count == 2
    names = sorted(p.name for p in output_dir.glob("*.md"))
    assert names == ["2026-01-15 Duplicate (1).md", "2026-01-15 Duplicate.md"]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def test_parse_iso_valid() -> None:
    dt = _parse_iso("2026-01-15T10:30:00Z")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 1 and dt.day == 15


def test_parse_iso_empty() -> None:
    assert _parse_iso("") is None


def test_parse_iso_invalid() -> None:
    assert _parse_iso("not-a-date") is None


def test_parse_response_time_string() -> None:
    dt = _parse_response_time("2026-03-01T12:00:00Z")
    assert dt is not None and dt.year == 2026


def test_parse_response_time_mongo_format() -> None:
    dt = _parse_response_time({"$date": {"$numberLong": "1700000000000"}})
    assert dt is not None


def test_parse_response_time_invalid_dict() -> None:
    assert _parse_response_time({"bad": "shape"}) is None


def test_parse_response_time_other_type() -> None:
    assert _parse_response_time(42) is None


def test_fmt_dt_formats_datetime() -> None:
    from datetime import datetime, timezone

    dt = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)
    assert _fmt_dt(dt) == "2026-05-01 09:30"


def test_fmt_dt_none_returns_empty() -> None:
    assert _fmt_dt(None) == ""


# ---------------------------------------------------------------------------
# File/extension helpers
# ---------------------------------------------------------------------------


def test_guess_extension_png() -> None:
    assert _guess_extension(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) == ".png"


def test_guess_extension_jpg() -> None:
    assert _guess_extension(b"\xff\xd8\xff" + b"\x00" * 100) == ".jpg"


def test_guess_extension_gif() -> None:
    assert _guess_extension(b"GIF89a" + b"\x00" * 100) == ".gif"


def test_guess_extension_webp() -> None:
    assert _guess_extension(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100) == ".webp"


def test_guess_extension_pdf() -> None:
    assert _guess_extension(b"%PDF-1.4" + b"\x00" * 100) == ".pdf"


def test_guess_extension_zip() -> None:
    assert _guess_extension(b"PK\x03\x04" + b"\x00" * 100) == ".zip"


def test_guess_extension_text() -> None:
    assert _guess_extension(b"Hello, world! " * 100) == ".txt"


def test_guess_extension_binary() -> None:
    assert _guess_extension(bytes(range(256)) * 10) == ".bin"


def test_guess_extension_empty() -> None:
    assert _guess_extension(b"") == ".bin"


def test_is_image_ext_true() -> None:
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        assert _is_image_ext(ext)


def test_is_image_ext_false() -> None:
    for ext in (".pdf", ".txt", ".zip", ".mp4"):
        assert not _is_image_ext(ext)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def test_clean_message_text_strips_render_markup() -> None:
    result = _clean_message_text("Hello $\\text{world}$ done")
    assert "Hello" in result
    assert "done" in result


def test_clean_message_text_plain() -> None:
    assert _clean_message_text("plain text") == "plain text"


# ---------------------------------------------------------------------------
# Collector helpers
# ---------------------------------------------------------------------------


def _resp(response: dict[str, Any]) -> dict[str, Any]:
    return {"response": response}


def test_collect_web_resources_basic() -> None:
    items = [
        _resp(
            {
                "web_search_results": [
                    {"title": "Example", "url": "https://example.com"},
                ]
            }
        )
    ]
    resources = _collect_web_resources(items)
    assert resources == [{"title": "Example", "url": "https://example.com"}]


def test_collect_web_resources_deduplicates() -> None:
    entry = {"title": "Dup", "url": "https://dup.com"}
    items = [_resp({"web_search_results": [entry, entry]})]
    assert len(_collect_web_resources(items)) == 1


def test_collect_web_resources_skips_missing_fields() -> None:
    items = [_resp({"web_search_results": [{"title": "", "url": "https://x.com"}]})]
    assert _collect_web_resources(items) == []


def test_collect_share_links() -> None:
    items = [{"share_link": {"share_link_id": "abc123"}}]
    links = _collect_share_links(items)
    assert links == ["https://grok.com/share/abc123"]


def test_collect_share_links_deduplicates() -> None:
    item = {"share_link": {"share_link_id": "abc"}}
    assert len(_collect_share_links([item, item])) == 1


def test_collect_webpage_urls() -> None:
    items = [_resp({"webpage_urls": ["https://a.com", "https://b.com"]})]
    assert _collect_webpage_urls(items) == ["https://a.com", "https://b.com"]


def test_collect_xpost_urls() -> None:
    items = [_resp({"xpost_ids": ["12345"]})]
    urls = _collect_xpost_urls(items)
    assert urls == ["https://x.com/i/web/status/12345"]


def test_collect_queries() -> None:
    items = [
        _resp({"query": "weather today", "query_type": "web"}),
        _resp({"query": "weather today", "query_type": "web"}),  # duplicate
        _resp({"query": "news", "query_type": "web"}),
    ]
    queries, types = _collect_queries(items)
    assert queries == ["weather today", "news"]
    assert types == ["web"]


def test_collect_generated_image_urls() -> None:
    items = [_resp({"generated_image_urls": ["https://img.com/a.png"]})]
    assert _collect_generated_image_urls(items) == ["https://img.com/a.png"]


def test_collect_image_edit_uris() -> None:
    items = [_resp({"image_edit_uri": "edit://abc"})]
    assert _collect_image_edit_uris(items) == ["edit://abc"]


def test_collect_media_types() -> None:
    conv = {"media_types": ["image"]}
    items = [_resp({"media_types": ["video", "image"]})]
    types = _collect_media_types(conv, items)
    assert "image" in types
    assert "video" in types
    assert types.count("image") == 1  # no duplicates


# ---------------------------------------------------------------------------
# load_conversations
# ---------------------------------------------------------------------------

UUID = "a1b2c3d4-0000-0000-0000-000000000001"
ASSET_ZIP_PATH = f"assets/prod-mc-asset-server//{UUID}/content"


def _make_export_zip(tmp_path: Path, payload: dict[str, Any]) -> Path:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))
    return zip_path


def test_load_conversations_returns_list(tmp_path: Path) -> None:
    convos = [{"conversation": {"id": "c1"}, "responses": []}]
    zip_path = _make_export_zip(tmp_path, {"conversations": convos})
    assert load_conversations(zip_path) == convos


def test_load_conversations_empty_key(tmp_path: Path) -> None:
    zip_path = _make_export_zip(tmp_path, {})
    assert load_conversations(zip_path) == []


def test_load_conversations_missing_backend_raises(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("other.json", "{}")
    with pytest.raises(FileNotFoundError, match="prod-grok-backend.json"):
        load_conversations(zip_path)


# ---------------------------------------------------------------------------
# _extract_attachments
# ---------------------------------------------------------------------------


def _make_asset_zip(
    tmp_path: Path, asset_data: bytes = b"\x89PNG\r\n\x1a\n"
) -> tuple[Path, str]:
    """Return (zip_path, uuid) with one PNG asset entry."""
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", "{}")
        zf.writestr(ASSET_ZIP_PATH, asset_data)
    return zip_path, UUID


def test_extract_attachments_no_modes_returns_empty(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [{"response": {"file_attachments": [uuid]}}],
    }
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item, zf, asset_paths, tmp_path / "note.md", tmp_path, set()
        )
    assert result == []


def test_extract_attachments_no_root_returns_empty(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [{"response": {"file_attachments": [uuid]}}],
    }
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item, zf, asset_paths, tmp_path / "note.md", None, {"files"}
        )
    assert result == []


def test_extract_attachments_writes_file(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [
            {
                "response": {
                    "file_attachments": [uuid],
                    "create_time": "2025-01-01T00:00:00Z",
                }
            }
        ],
    }
    out_root = tmp_path / "attachments"
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item, zf, asset_paths, tmp_path / "note.md", out_root, {"files"}
        )

    assert len(result) == 1
    assert result[0]["kind"] == "image"
    assert result[0]["label"].endswith(".png")
    assert (out_root / "c1" / result[0]["label"]).exists()


def test_extract_attachments_skips_missing_asset(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [{"response": {"file_attachments": ["no-such-uuid"]}}],
    }
    out_root = tmp_path / "attachments"
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item, zf, asset_paths, tmp_path / "note.md", out_root, {"files"}
        )
    assert result == []


def test_extract_attachments_deduplicates(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [
            {"response": {"file_attachments": [uuid]}},
            {"response": {"file_attachments": [uuid]}},  # same asset twice
        ],
    }
    out_root = tmp_path / "attachments"
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item, zf, asset_paths, tmp_path / "note.md", out_root, {"files"}
        )
    assert len(result) == 1


def test_extract_attachments_edited_images_mode(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [{"response": {"image_edit_uri": f"some://path/{uuid}/foo"}}],
    }
    out_root = tmp_path / "attachments"
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item,
            zf,
            asset_paths,
            tmp_path / "note.md",
            out_root,
            {"edited-images"},
        )
    assert len(result) == 1
    assert result[0]["kind"] == "image"


def test_extract_attachments_generated_images_mode(tmp_path: Path) -> None:
    zip_path, uuid = _make_asset_zip(tmp_path)
    conv_item = {
        "conversation": {"id": "c1"},
        "responses": [
            {
                "response": {
                    "generated_image_urls": [f"https://cdn.example.com/{uuid}/img"]
                }
            }
        ],
    }
    out_root = tmp_path / "attachments"
    with zipfile.ZipFile(zip_path) as zf:
        asset_paths = {uuid: ASSET_ZIP_PATH}
        result = _extract_attachments(
            conv_item,
            zf,
            asset_paths,
            tmp_path / "note.md",
            out_root,
            {"generated-images"},
        )
    assert len(result) == 1
    assert result[0]["kind"] == "image"


# ---------------------------------------------------------------------------
# _asset_index
# ---------------------------------------------------------------------------


def test_asset_index_finds_assets(tmp_path: Path) -> None:
    from grokko.extract import _asset_index

    zip_path, uuid = _make_asset_zip(tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        index = _asset_index(zf)
    assert uuid in index
    assert index[uuid] == ASSET_ZIP_PATH


def test_asset_index_ignores_non_asset_entries(tmp_path: Path) -> None:
    from grokko.extract import _asset_index

    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", "{}")
        zf.writestr("unrelated/file.txt", "data")
    with zipfile.ZipFile(zip_path) as zf:
        index = _asset_index(zf)
    assert index == {}


# ---------------------------------------------------------------------------
# _guess_extension - non-UTF8 binary
# ---------------------------------------------------------------------------


def test_guess_extension_non_utf8_binary() -> None:
    from grokko.extract import _guess_extension

    data = bytes([0x80, 0x81, 0x82, 0x83] * 200)
    assert _guess_extension(data) == ".bin"


# ---------------------------------------------------------------------------
# _collect_web_resources - card_attachments branch
# ---------------------------------------------------------------------------


def test_collect_web_resources_citation_card(tmp_path: Path) -> None:
    card = json.dumps(
        {"cardType": "citation_card", "url": "https://cite.com", "title": "Cited"}
    )
    items = [{"response": {"card_attachments_json": [card]}}]
    resources = _collect_web_resources(items)
    assert resources == [{"title": "Cited", "url": "https://cite.com"}]


def test_collect_web_resources_non_citation_card_skipped(tmp_path: Path) -> None:
    card = json.dumps({"cardType": "other_card", "url": "https://other.com"})
    items = [{"response": {"card_attachments_json": [card]}}]
    assert _collect_web_resources(items) == []


def test_collect_web_resources_invalid_json_skipped() -> None:
    items = [{"response": {"card_attachments_json": ["not-json"]}}]
    assert _collect_web_resources(items) == []


def test_collect_web_resources_cited_results_key() -> None:
    items = [
        {
            "response": {
                "cited_web_search_results": [
                    {"title": "Cited result", "URL": "https://cited.com"}
                ]
            }
        }
    ]
    resources = _collect_web_resources(items)
    assert resources == [{"title": "Cited result", "url": "https://cited.com"}]


# ---------------------------------------------------------------------------
# _render_note - frontmatter branches
# ---------------------------------------------------------------------------


def _make_note_zip(tmp_path: Path, conv_item: dict[str, Any]) -> Path:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "prod-grok-backend.json",
            json.dumps({"conversations": [conv_item]}),
        )
    return zip_path


def test_render_note_starred_and_temporary(tmp_path: Path) -> None:
    from grokko.extract import GrokExtractManager

    conv_item = {
        "conversation": {
            "id": "c1",
            "title": "Starred",
            "create_time": "2026-01-01T00:00:00Z",
            "starred": True,
            "temporary": True,
        },
        "responses": [],
    }
    zip_path = _make_note_zip(tmp_path, conv_item)
    out = tmp_path / "out"
    GrokExtractManager(zip_path).export(out)
    content = list(out.glob("*.md"))[0].read_text()
    assert "starred: true" in content
    assert "temporary: true" in content


def test_render_note_system_prompt(tmp_path: Path) -> None:
    from grokko.extract import GrokExtractManager

    conv_item = {
        "conversation": {
            "id": "c2",
            "title": "Prompted",
            "create_time": "2026-01-01T00:00:00Z",
            "system_prompt_name": "Custom Prompt",
        },
        "responses": [],
    }
    zip_path = _make_note_zip(tmp_path, conv_item)
    out = tmp_path / "out"
    GrokExtractManager(zip_path).export(out)
    content = list(out.glob("*.md"))[0].read_text()
    assert "system_prompt:" in content
    assert "Custom Prompt" in content


def test_render_note_single_attachment(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c3",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [],
    }
    attachments = [
        {"label": "img.png", "path": "attachments/c3/img.png", "kind": "image"}
    ]
    content = _render_note(conv_item, attachments=attachments)
    assert "attachment_file:" in content
    assert "attachment_count: 1" in content
    assert "![](" in content


def test_render_note_multiple_attachments(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c4",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [],
    }
    attachments = [
        {"label": "a.png", "path": "att/a.png", "kind": "image"},
        {"label": "b.txt", "path": "att/b.txt", "kind": "file"},
    ]
    content = _render_note(conv_item, attachments=attachments)
    assert "attachment_files:" in content
    assert "attachment_count: 2" in content
    assert "![](" in content
    assert "- [b.txt](" in content


def test_render_note_single_share_link(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c5",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {}, "share_link": {"share_link_id": "abc123"}}],
    }
    content = _render_note(conv_item)
    assert "share_link:" in content
    assert "abc123" in content


def test_render_note_multiple_share_links(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c6",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [
            {"response": {}, "share_link": {"share_link_id": "aaa"}},
            {"response": {}, "share_link": {"share_link_id": "bbb"}},
        ],
    }
    content = _render_note(conv_item)
    assert "share_links:" in content


def test_render_note_single_query(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c7",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {"query": "hello world", "query_type": "web"}}],
    }
    content = _render_note(conv_item)
    assert 'query: "hello world"' in content
    assert "query_type: web" in content


def test_render_note_multiple_queries(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c8",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [
            {"response": {"query": "q1", "query_type": "web"}},
            {"response": {"query": "q2", "query_type": "image"}},
        ],
    }
    content = _render_note(conv_item)
    assert "queries:" in content
    assert "query_types:" in content


def test_render_note_single_image_edit_uri(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c9",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {"image_edit_uri": "edit://abc"}}],
    }
    content = _render_note(conv_item)
    assert "image_edit_uri:" in content


def test_render_note_multiple_image_edit_uris(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c10",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [
            {"response": {"image_edit_uri": "edit://a"}},
            {"response": {"image_edit_uri": "edit://b"}},
        ],
    }
    content = _render_note(conv_item)
    assert "image_edit_uris:" in content


def test_render_note_single_media_type(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c11",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
            "media_types": ["image"],
        },
        "responses": [],
    }
    content = _render_note(conv_item)
    assert "media_type: image" in content


def test_render_note_multiple_media_types(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c12",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
            "media_types": ["image", "video"],
        },
        "responses": [],
    }
    content = _render_note(conv_item)
    assert "media_types:" in content


def test_render_note_web_resources_section(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c13",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
            "summary": "A nice summary",
        },
        "responses": [
            {
                "response": {
                    "web_search_results": [
                        {"title": "Example", "url": "https://ex.com"}
                    ]
                }
            }
        ],
    }
    content = _render_note(conv_item)
    assert "<details>" in content
    assert "Web resources" in content
    assert "A nice summary" in content
    assert "[Example](https://ex.com)" in content


def test_render_note_webpage_urls_section(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c14",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {"webpage_urls": ["https://page.com"]}}],
    }
    content = _render_note(conv_item)
    assert "Referenced pages" in content
    assert "https://page.com" in content


def test_render_note_xpost_urls_section(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c15",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {"xpost_ids": ["9876"]}}],
    }
    content = _render_note(conv_item)
    assert "X posts" in content
    assert "x.com/i/web/status/9876" in content


def test_render_note_generated_images_section(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c16",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [
            {"response": {"generated_image_urls": ["https://img.com/a.png"]}}
        ],
    }
    content = _render_note(conv_item)
    assert "Image references" in content
    assert "Generated image:" in content


def test_render_note_no_models(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c17",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [{"response": {"sender": "human", "message": "hi"}}],
    }
    content = _render_note(conv_item)
    assert "models: []" in content


def test_render_note_webpage_and_xpost_count_in_frontmatter(tmp_path: Path) -> None:
    from grokko.extract import _render_note

    conv_item = {
        "conversation": {
            "id": "c18",
            "title": "T",
            "create_time": "2026-01-01T00:00:00Z",
        },
        "responses": [
            {
                "response": {
                    "webpage_urls": ["https://a.com"],
                    "xpost_ids": ["111"],
                    "generated_image_urls": ["https://img.com/x.png"],
                }
            }
        ],
    }
    content = _render_note(conv_item)
    assert "webpage_url_count: 1" in content
    assert "xpost_count: 1" in content
    assert "generated_image_count: 1" in content
