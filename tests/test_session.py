"""Tests for GrokSessionManager non-browser helpers."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grokko.config import GrokSessionConfig
from grokko.session import GrokSessionManager


def _manager(tmp_path: Path) -> GrokSessionManager:
    return GrokSessionManager(config=GrokSessionConfig(storage_dir=tmp_path))


# ---------------------------------------------------------------------------
# looks_like_login_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://grok.com/sign-in",
        "https://example.com/login",
        "https://x.com/i/flow/login",
        "https://twitter.com/i/flow/login",
        "https://accounts.example.com/oauth/authorize",
        "https://example.com/auth/callback",
        "https://EXAMPLE.COM/LOGIN",  # case-insensitive
    ],
)
def test_looks_like_login_url_true(tmp_path: Path, url: str) -> None:
    assert _manager(tmp_path).looks_like_login_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://grok.com/",
        "https://grok.com/chat/abc123",
        "https://example.com/profile",
        "",
    ],
)
def test_looks_like_login_url_false(tmp_path: Path, url: str) -> None:
    assert _manager(tmp_path).looks_like_login_url(url) is False


# ---------------------------------------------------------------------------
# print_cookie_report
# ---------------------------------------------------------------------------


def test_print_cookie_report_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _manager(tmp_path).print_cookie_report(tmp_path / "nonexistent.json")
    assert "No state file found" in capsys.readouterr().err


def test_print_cookie_report_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "auth.json"
    bad.write_text("not json", encoding="utf-8")
    _manager(tmp_path).print_cookie_report(bad)
    assert "Could not parse" in capsys.readouterr().err


def test_print_cookie_report_no_cookies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "auth.json"
    state.write_text(json.dumps({"cookies": []}), encoding="utf-8")
    _manager(tmp_path).print_cookie_report(state)
    assert "No cookies found" in capsys.readouterr().err


def test_print_cookie_report_session_cookie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "auth.json"
    state.write_text(
        json.dumps(
            {"cookies": [{"name": "token", "domain": "grok.com", "expires": -1}]}
        ),
        encoding="utf-8",
    )
    _manager(tmp_path).print_cookie_report(state)
    out = capsys.readouterr().out
    assert "token" in out
    assert "session/non-persistent" in out


def test_print_cookie_report_persistent_cookie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import time

    future = time.time() + 86400 * 30  # 30 days from now
    state = tmp_path / "auth.json"
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "auth_token", "domain": "grok.com", "expires": future}
                ]
            }
        ),
        encoding="utf-8",
    )
    _manager(tmp_path).print_cookie_report(state)
    out = capsys.readouterr().out
    assert "auth_token" in out
    assert "days" in out


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def test_inspect_calls_print_cookie_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)
    with patch.object(mgr, "print_cookie_report") as mock_report:
        mgr.inspect()
    mock_report.assert_called_once_with(mgr.config.state_file)


# ---------------------------------------------------------------------------
# capture_from_chrome_cookies
# ---------------------------------------------------------------------------


def test_capture_from_chrome_cookies_import_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)
    with patch.dict("sys.modules", {"browser_cookie3": None}):
        result = mgr.capture_from_chrome_cookies()
    assert result is False
    assert "browser-cookie3" in capsys.readouterr().err


def test_capture_from_chrome_cookies_chrome_read_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)
    mock_bc3 = MagicMock()
    mock_bc3.chrome.side_effect = RuntimeError("no chrome")
    with patch.dict("sys.modules", {"browser_cookie3": mock_bc3}):
        result = mgr.capture_from_chrome_cookies()
    assert result is False
    assert "Failed to read Chrome cookies" in capsys.readouterr().err


def test_capture_from_chrome_cookies_no_matching_cookies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)
    fake_cookie = MagicMock()
    fake_cookie.domain = "unrelated.com"

    mock_bc3 = MagicMock()
    mock_bc3.chrome.return_value = [fake_cookie]
    with patch.dict("sys.modules", {"browser_cookie3": mock_bc3}):
        result = mgr.capture_from_chrome_cookies()
    assert result is False
    assert "No cookies found" in capsys.readouterr().err


def test_capture_from_chrome_cookies_saves_state_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)

    fake_cookie = MagicMock()
    fake_cookie.domain = ".grok.com"
    fake_cookie.name = "auth_token"
    fake_cookie.value = "secret"
    fake_cookie.path = "/"
    fake_cookie.expires = 9999999999
    fake_cookie.secure = True

    mock_bc3 = MagicMock()
    mock_bc3.chrome.return_value = [fake_cookie]
    with patch.dict("sys.modules", {"browser_cookie3": mock_bc3}):
        result = mgr.capture_from_chrome_cookies()

    assert result is True
    state = json.loads(mgr.config.state_file.read_text())
    assert len(state["cookies"]) == 1
    assert state["cookies"][0]["name"] == "auth_token"
    assert "Saved 1 cookies" in capsys.readouterr().err


def test_capture_from_chrome_cookies_no_expires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mgr = _manager(tmp_path)

    fake_cookie = MagicMock()
    fake_cookie.domain = "x.ai"
    fake_cookie.name = "session"
    fake_cookie.value = "val"
    fake_cookie.path = "/"
    fake_cookie.expires = None
    fake_cookie.secure = False

    mock_bc3 = MagicMock()
    mock_bc3.chrome.return_value = [fake_cookie]
    with patch.dict("sys.modules", {"browser_cookie3": mock_bc3}):
        result = mgr.capture_from_chrome_cookies()

    assert result is True
    state = json.loads(mgr.config.state_file.read_text())
    assert state["cookies"][0]["expires"] == -1


# ---------------------------------------------------------------------------
# Delegate methods (inspect_zip, request_data_export, etc.)
# ---------------------------------------------------------------------------


def test_inspect_zip_delegates_to_export_manager(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("prod-grok-backend.json", json.dumps({"conversations": []}))

    result = mgr.inspect_zip(zip_path)
    assert result is True


def test_request_data_export_delegates(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    with patch(
        "grokko.export.GrokExportManager.request_data_export", return_value=True
    ) as mock_req:
        result = mgr.request_data_export()
    assert result is True
    mock_req.assert_called_once()


def test_download_export_file_delegates(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    expected = tmp_path / "out.zip"
    with patch(
        "grokko.export.GrokExportManager.download_export_file", return_value=expected
    ) as mock_dl:
        result = mgr.download_export_file("https://dl.example.com/x.zip")
    assert result == expected
    mock_dl.assert_called_once()


def test_poll_for_export_url_delegates(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    mgr = _manager(tmp_path)
    after = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch(
        "grokko.export.GrokExportManager.poll_for_export_url",
        return_value="https://url",
    ):
        result = mgr.poll_for_export_url(after)
    assert result == "https://url"


def test_export_and_download_delegates(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    expected = tmp_path / "archive.zip"
    with patch(
        "grokko.export.GrokExportManager.export_and_download", return_value=expected
    ):
        result = mgr.export_and_download()
    assert result == expected
