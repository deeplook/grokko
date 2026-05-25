"""Tests for GrokExportManager non-browser helpers."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from grokko.config import GrokExportConfig, GrokSessionConfig
from grokko.export import GrokExportManager
from grokko.session import GrokSessionManager


def _export_manager(tmp_path: Path) -> GrokExportManager:
    session = GrokSessionManager(config=GrokSessionConfig(storage_dir=tmp_path))
    return GrokExportManager(session)


def _make_zip(tmp_path: Path, payload: dict[str, Any]) -> Path:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps(payload))
    return zip_path


# ---------------------------------------------------------------------------
# inspect_zip
# ---------------------------------------------------------------------------


def test_inspect_zip_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = _export_manager(tmp_path).inspect_zip(tmp_path / "missing.zip")
    assert result is False
    assert "not found" in capsys.readouterr().err.lower()


def test_inspect_zip_no_backend_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("other.json", "{}")
    result = _export_manager(tmp_path).inspect_zip(zip_path)
    assert result is False
    assert "prod-grok-backend.json" in capsys.readouterr().err


def test_inspect_zip_invalid_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    result = _export_manager(tmp_path).inspect_zip(bad)
    assert result is False
    assert "Could not read ZIP" in capsys.readouterr().err


def test_inspect_zip_empty_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zip_path = _make_zip(tmp_path, {"conversations": [], "projects": [], "tasks": []})
    result = _export_manager(tmp_path).inspect_zip(zip_path)
    assert result is True
    out = capsys.readouterr().out
    assert "Conversations : 0" in out


def test_inspect_zip_counts_and_dates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "conversations": [
            {"conversation": {"create_time": "2025-01-01T10:00:00Z"}},
            {"conversation": {"create_time": "2025-06-15T12:00:00Z"}},
        ],
        "projects": [{}],
        "tasks": [{}, {}],
        "media_posts": [{}],
    }
    zip_path = _make_zip(tmp_path, payload)
    result = _export_manager(tmp_path).inspect_zip(zip_path)
    assert result is True
    out = capsys.readouterr().out
    assert "Conversations : 2" in out
    assert "Projects      : 1" in out
    assert "Tasks         : 2" in out
    assert "Earliest      : 2025-01-01" in out
    assert "Latest        : 2025-06-15" in out


def test_inspect_zip_invalid_json_inside_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zip_path = tmp_path / "bad_json.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", "not-json{{{")
    result = _export_manager(tmp_path).inspect_zip(zip_path)
    assert result is False
    assert "Could not read ZIP" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# poll_for_export_url
# ---------------------------------------------------------------------------


def test_poll_for_export_url_returns_url_on_first_attempt(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    after = datetime(2026, 5, 1, tzinfo=timezone.utc)
    cfg = GrokExportConfig(imap_user="u@e.com", imap_password="p")

    with patch(
        "grokko.export.find_url_in_email",
        return_value="https://dl.example.com/export.zip",
    ) as mock_find:
        url = mgr.poll_for_export_url(after, export_config=cfg)

    assert url == "https://dl.example.com/export.zip"
    mock_find.assert_called_once()


def test_poll_for_export_url_times_out_when_no_url(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    after = datetime(2026, 5, 1, tzinfo=timezone.utc)
    cfg = GrokExportConfig(
        imap_user="u@e.com", imap_password="p", poll_timeout=0, poll_interval=1
    )

    with patch("grokko.export.find_url_in_email", return_value=None):
        url = mgr.poll_for_export_url(after, export_config=cfg)

    assert url is None


def test_poll_for_export_url_retries_until_found(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    after = datetime(2026, 5, 1, tzinfo=timezone.utc)
    cfg = GrokExportConfig(
        imap_user="u@e.com", imap_password="p", poll_timeout=10, poll_interval=1
    )

    side_effects = [None, None, "https://found.example.com/export.zip"]

    with (
        patch("grokko.export.find_url_in_email", side_effect=side_effects),
        patch("grokko.export.time.sleep"),
    ):
        url = mgr.poll_for_export_url(after, export_config=cfg)

    assert url == "https://found.example.com/export.zip"


# ---------------------------------------------------------------------------
# export_and_download
# ---------------------------------------------------------------------------


def test_export_and_download_aborts_when_request_fails(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    cfg = GrokExportConfig(imap_user="u@e.com", imap_password="p")

    with patch.object(mgr, "request_data_export", return_value=False):
        result = mgr.export_and_download(export_config=cfg)

    assert result is None


def test_export_and_download_aborts_when_poll_fails(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    cfg = GrokExportConfig(imap_user="u@e.com", imap_password="p")

    with (
        patch.object(mgr, "request_data_export", return_value=True),
        patch.object(mgr, "poll_for_export_url", return_value=None),
    ):
        result = mgr.export_and_download(export_config=cfg)

    assert result is None


def test_export_and_download_returns_path_on_success(tmp_path: Path) -> None:
    mgr = _export_manager(tmp_path)
    cfg = GrokExportConfig(imap_user="u@e.com", imap_password="p")
    expected = tmp_path / "grok-export.zip"

    with (
        patch.object(mgr, "request_data_export", return_value=True),
        patch.object(
            mgr, "poll_for_export_url", return_value="https://dl.example.com/x.zip"
        ),
        patch.object(mgr, "download_export_file", return_value=expected) as mock_dl,
    ):
        result = mgr.export_and_download(export_config=cfg, dest=tmp_path)

    assert result == expected
    mock_dl.assert_called_once_with(
        "https://dl.example.com/x.zip", dest=tmp_path, headless=False
    )
