"""Tests for the grokko.attachments module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from grokko.attachments import Attachment, collect_attachments, download_attachments

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FILE_META = {
    "fileMetadataId": "file-uuid-1",
    "fileMimeType": "image/png",
    "fileName": "grafik.png",
    "fileUri": "users/user-123/file-uuid-1/content",
}

CARD_PARTIAL = json.dumps(
    {
        "id": "cardA",
        "cardType": "generated_image_card",
        "image_chunk": {
            "imageUuid": "img-uuid-1",
            "imageUrl": "users/user-123/generated/img-uuid-1-part-0/image.jpg",
            "seq": 0,
            "progress": 50,
        },
    }
)

CARD_COMPLETE = json.dumps(
    {
        "id": "cardA",
        "cardType": "generated_image_card",
        "image_chunk": {
            "imageUuid": "img-uuid-1",
            "imageUrl": "users/user-123/generated/img-uuid-1/image.jpg",
            "seq": 1,
            "progress": 100,
        },
    }
)

CARD_COMPLETE_2 = json.dumps(
    {
        "id": "cardB",
        "cardType": "generated_image_card",
        "image_chunk": {
            "imageUuid": "img-uuid-2",
            "imageUrl": "users/user-123/generated/img-uuid-2/image.jpg",
            "seq": 1,
            "progress": 100,
        },
    }
)

HUMAN_RESPONSE = {
    "sender": "human",
    "message": "Convert this.",
    "fileAttachmentsMetadata": [FILE_META],
    "cardAttachmentsJson": [],
}

ASSISTANT_RESPONSE = {
    "sender": "ASSISTANT",
    "message": "Done.",
    "fileAttachmentsMetadata": [],
    "cardAttachmentsJson": [CARD_PARTIAL, CARD_COMPLETE],
}


# ---------------------------------------------------------------------------
# collect_attachments
# ---------------------------------------------------------------------------


def test_collect_uploaded_file() -> None:
    atts = collect_attachments([HUMAN_RESPONSE])
    assert len(atts) == 1
    att = atts[0]
    assert att.filename == "grafik.png"
    assert att.kind == "image"
    assert att.url == "https://assets.grok.com/users/user-123/file-uuid-1/content"


def test_collect_non_image_file_kind() -> None:
    resp = {
        "fileAttachmentsMetadata": [
            {
                "fileMimeType": "application/octet-stream",
                "fileName": "data.xmind",
                "fileUri": "users/user-123/file-uuid-2/content",
            }
        ],
        "cardAttachmentsJson": [],
    }
    atts = collect_attachments([resp])
    assert atts[0].kind == "file"


def test_collect_generated_image_skips_partial() -> None:
    resp = {
        "fileAttachmentsMetadata": [],
        "cardAttachmentsJson": [CARD_PARTIAL],
    }
    atts = collect_attachments([resp])
    assert atts == []


def test_collect_generated_image_takes_complete() -> None:
    atts = collect_attachments([ASSISTANT_RESPONSE])
    assert len(atts) == 1
    att = atts[0]
    assert att.filename == "img-uuid-1.jpg"
    assert att.kind == "image"
    assert (
        att.url
        == "https://assets.grok.com/users/user-123/generated/img-uuid-1/image.jpg"
    )


def test_collect_deduplicates_image_uuid() -> None:
    # Same imageUuid appearing in two separate responses
    resp1 = {"fileAttachmentsMetadata": [], "cardAttachmentsJson": [CARD_COMPLETE]}
    resp2 = {"fileAttachmentsMetadata": [], "cardAttachmentsJson": [CARD_COMPLETE]}
    atts = collect_attachments([resp1, resp2])
    assert len(atts) == 1


def test_collect_deduplicates_file_uri() -> None:
    atts = collect_attachments([HUMAN_RESPONSE, HUMAN_RESPONSE])
    assert len(atts) == 1


def test_collect_multiple_responses() -> None:
    atts = collect_attachments([HUMAN_RESPONSE, ASSISTANT_RESPONSE])
    assert len(atts) == 2
    filenames = {a.filename for a in atts}
    assert "grafik.png" in filenames
    assert "img-uuid-1.jpg" in filenames


def test_collect_two_distinct_generated_images() -> None:
    resp = {
        "fileAttachmentsMetadata": [],
        "cardAttachmentsJson": [CARD_COMPLETE, CARD_COMPLETE_2],
    }
    atts = collect_attachments([resp])
    assert len(atts) == 2


def test_collect_empty_responses() -> None:
    assert collect_attachments([]) == []


def test_collect_response_missing_fields() -> None:
    assert collect_attachments([{"sender": "human", "message": "hi"}]) == []


def test_collect_malformed_card_json_skipped() -> None:
    resp = {
        "fileAttachmentsMetadata": [],
        "cardAttachmentsJson": ["{not valid json"],
    }
    assert collect_attachments([resp]) == []


def test_collect_card_missing_image_chunk_skipped() -> None:
    resp = {
        "fileAttachmentsMetadata": [],
        "cardAttachmentsJson": [json.dumps({"id": "x", "image_chunk": {}})],
    }
    assert collect_attachments([resp]) == []


def test_collect_file_missing_uri_skipped() -> None:
    resp = {
        "fileAttachmentsMetadata": [
            {"fileMimeType": "image/png", "fileName": "f.png", "fileUri": ""}
        ],
        "cardAttachmentsJson": [],
    }
    assert collect_attachments([resp]) == []


# ---------------------------------------------------------------------------
# download_attachments
# ---------------------------------------------------------------------------


_FAKE_ATT = Attachment(
    url="https://assets.grok.com/u/f.png", filename="f.png", kind="image"
)


def _make_mock_context(
    status: int = 200, body: bytes = b"fake-image-data"
) -> MagicMock:
    """Build a minimal mock for a Playwright APIRequestContext."""
    mock_resp = MagicMock()
    mock_resp.ok = status < 400
    mock_resp.status = status
    mock_resp.body.return_value = body
    mock_ctx = MagicMock()
    mock_ctx.request.get.return_value = mock_resp
    return mock_ctx


def _run_download(
    atts: list[Attachment],
    out: Path,
    auth: Path,
    mock_ctx: MagicMock,
) -> int:
    """Run download_attachments with the Playwright context mocked."""
    with patch("playwright.sync_api.sync_playwright") as mock_pw:
        pw = mock_pw.return_value.__enter__.return_value
        pw.chromium.launch.return_value.new_context.return_value = mock_ctx
        return download_attachments(atts, out, auth)


def test_download_writes_files(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    out = tmp_path / "out"
    count = _run_download([_FAKE_ATT], out, auth, _make_mock_context(body=b"\x89PNG"))
    assert count == 1
    assert (out / "f.png").read_bytes() == b"\x89PNG"


def test_download_skips_existing_file(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "f.png"
    existing.write_bytes(b"old")
    mock_ctx = _make_mock_context()
    count = _run_download([_FAKE_ATT], out, auth, mock_ctx)
    assert count == 0
    assert existing.read_bytes() == b"old"
    mock_ctx.request.get.assert_not_called()


def test_download_handles_http_error(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    out = tmp_path / "out"
    count = _run_download([_FAKE_ATT], out, auth, _make_mock_context(status=403))
    assert count == 0
    assert not (out / "f.png").exists()


def test_download_returns_partial_count_on_mixed_results(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    out = tmp_path / "out"

    base = "https://assets.grok.com/u"
    atts = [
        Attachment(url=f"{base}/a.png", filename="a.png", kind="image"),
        Attachment(url=f"{base}/b.png", filename="b.png", kind="image"),
    ]

    ok_resp = MagicMock(ok=True, status=200)
    ok_resp.body.return_value = b"data"
    fail_resp = MagicMock(ok=False, status=404)
    mock_ctx = MagicMock()
    mock_ctx.request.get.side_effect = [ok_resp, fail_resp]

    count = _run_download(atts, out, auth, mock_ctx)
    assert count == 1
    assert (out / "a.png").exists()
    assert not (out / "b.png").exists()
