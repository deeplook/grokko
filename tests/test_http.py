from __future__ import annotations

import io
import json
import uuid
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from grokko import _http
from grokko._http import GrokApiError, GrokRestClient, build_cookie_header, extract_list


def test_build_cookie_header_filters_for_grok_domain() -> None:
    cookies = [
        {"domain": ".grok.com", "name": "a", "value": "1"},
        {"domain": ".x.ai", "name": "b", "value": "2"},
        {"domain": ".grok.com", "name": "", "value": "3"},
    ]

    assert build_cookie_header(cookies) == "a=1"


def test_extract_list_supports_common_response_shapes() -> None:
    assert extract_list([{"id": 1}], "conversations") == [{"id": 1}]
    assert extract_list({"conversations": [{"id": 2}]}, "conversations") == [{"id": 2}]
    assert extract_list({"items": [{"id": 3}]}, "conversations") == [{"id": 3}]
    assert extract_list({"results": [{"id": 4}]}, "conversations") == [{"id": 4}]
    assert extract_list({"data": [{"id": 5}]}, "conversations") == [{"id": 5}]


def test_extract_list_rejects_unexpected_shape() -> None:
    with pytest.raises(GrokApiError):
        extract_list({"nope": "bad"}, "conversations")


def test_rest_client_get_and_post_delegate_to_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GrokRestClient([], "ua")
    calls: list[tuple[str, str, object | None]] = []

    def fake_request(
        method: str, path: str, body: object | None = None
    ) -> dict[str, str]:
        calls.append((method, path, body))
        return {"ok": method}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client._get("/a") == {"ok": "GET"}
    assert client._post("/b", {"x": 1}) == {"ok": "POST"}
    assert calls == [("GET", "/a", None), ("POST", "/b", {"x": 1})]


def test_request_builds_headers_and_decodes_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GrokRestClient(
        [{"domain": ".grok.com", "name": "sso", "value": "abc"}], "ua"
    )
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req: Request, timeout: int) -> FakeResponse:
        captured["req"] = req
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(_http, "urlopen", fake_urlopen)
    monkeypatch.setattr(uuid, "uuid4", lambda: "req-123")

    payload = client._request("POST", "/rest/test", {"x": 1}, timeout=9)

    req: Request = captured["req"]
    assert payload == {"ok": True}
    assert captured["timeout"] == 9
    assert req.full_url == "https://grok.com/rest/test"
    assert req.get_method() == "POST"
    assert req.data == b'{"x": 1}'
    assert req.get_header("Cookie") == "sso=abc"
    assert req.get_header("User-agent") == "ua"
    assert req.get_header("X-xai-request-id") == "req-123"
    assert req.get_header("Accept") == "application/json"
    assert req.get_header("Content-type") == "application/json"


def test_request_wraps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GrokRestClient([], "ua")

    def fake_urlopen(req: object, timeout: int) -> object:
        raise HTTPError(
            url="https://grok.com/rest/test",
            code=403,
            msg="forbidden",
            hdrs=Message(),
            fp=io.BytesIO(b""),
        )

    monkeypatch.setattr(_http, "urlopen", fake_urlopen)

    with pytest.raises(GrokApiError, match="HTTP 403"):
        client._request("GET", "/rest/test")


def test_request_wraps_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GrokRestClient([], "ua")

    def fake_urlopen(req: object, timeout: int) -> object:
        raise URLError("no route")

    monkeypatch.setattr(_http, "urlopen", fake_urlopen)

    with pytest.raises(GrokApiError, match="Network error reaching"):
        client._request("GET", "/rest/test")
