"""Shared HTTP helpers for Grok's undocumented REST endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BASE = "https://grok.com"


class GrokApiError(Exception):
    """Raised when a Grok API request fails or returns an unexpected shape."""

    pass


class GrokRestClient:
    """Small REST client with Grok-specific headers and cookie handling."""

    def __init__(self, cookies: list[dict[str, Any]], user_agent: str) -> None:
        self._cookie_header = build_cookie_header(cookies)
        self._user_agent = user_agent

    def _get(self, path: str) -> Any:
        """Issue a JSON `GET` request against the Grok backend."""
        return self._request("GET", path)

    def _post(self, path: str, body: Any) -> Any:
        """Issue a JSON `POST` request against the Grok backend."""
        return self._request("POST", path, body)

    def _request(
        self, method: str, path: str, body: Any = None, *, timeout: int = 30
    ) -> Any:
        """Send one JSON request and decode the JSON response body."""
        url = _BASE + path
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header("Cookie", self._cookie_header)
        req.add_header("User-Agent", self._user_agent)
        req.add_header("x-xai-request-id", str(uuid.uuid4()))
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as exc:
            raise GrokApiError(
                f"HTTP {exc.code} from {url} — Grok API may have changed"
            ) from exc
        except URLError as exc:
            raise GrokApiError(f"Network error reaching {url}: {exc.reason}") from exc


def build_cookie_header(cookies: list[dict[str, Any]]) -> str:
    """Serialize Grok cookies into a `Cookie` header value."""
    parts: list[str] = []
    for cookie in cookies:
        domain = cookie.get("domain", "")
        if "grok.com" in domain:
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name:
                parts.append(f"{name}={value}")
    return "; ".join(parts)


def extract_list(resp: Any, hint_key: str) -> list[dict[str, Any]]:
    """Extract a list payload from one of the response shapes Grok uses."""
    if isinstance(resp, list):
        return cast(list[dict[str, Any]], resp)
    if isinstance(resp, dict):
        for key in (hint_key, "items", "results", "data"):
            if key in resp and isinstance(resp[key], list):
                return cast(list[dict[str, Any]], resp[key])
    raise GrokApiError(
        f"Unexpected API response shape — Grok API may have changed: "
        f"{json.dumps(resp)[:300]}"
    )
