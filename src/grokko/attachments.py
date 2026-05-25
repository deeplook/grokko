"""Download attachments from Grok conversation responses via Playwright."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

_ASSETS_BASE = "https://assets.grok.com"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class Attachment(NamedTuple):
    url: str
    filename: str
    kind: str  # "file" | "image"


def collect_attachments(responses: list[dict[str, Any]]) -> list[Attachment]:
    """Walk a list of response dicts and return all downloadable attachments."""
    import json

    attachments: list[Attachment] = []
    seen_urls: set[str] = set()
    seen_image_uuids: set[str] = set()

    for resp in responses:
        # Uploaded files (human messages)
        for meta in resp.get("fileAttachmentsMetadata", []):
            file_uri = (meta.get("fileUri") or "").strip()
            if not file_uri:
                continue
            url = f"{_ASSETS_BASE}/{file_uri}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            filename = (meta.get("fileName") or Path(file_uri).name).strip()
            mime = meta.get("fileMimeType", "")
            kind = "image" if mime.startswith("image/") else "file"
            attachments.append(Attachment(url=url, filename=filename, kind=kind))

        # Generated / edited images (assistant messages)
        for raw_card in resp.get("cardAttachmentsJson", []):
            try:
                card = json.loads(raw_card)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            chunk = card.get("image_chunk") or {}
            image_uuid = (chunk.get("imageUuid") or "").strip()
            image_url_path = (chunk.get("imageUrl") or "").strip()
            if not image_uuid or not image_url_path or chunk.get("progress", 0) < 100:
                continue
            if image_uuid in seen_image_uuids:
                continue
            seen_image_uuids.add(image_uuid)

            url = f"{_ASSETS_BASE}/{image_url_path}"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            ext = Path(image_url_path).suffix or ".jpg"
            attachments.append(
                Attachment(url=url, filename=f"{image_uuid}{ext}", kind="image")
            )

    return attachments


def download_attachments(
    attachments: list[Attachment],
    output_dir: Path,
    auth_path: Path,
) -> int:
    """Download attachments to output_dir using a Playwright browser context.

    Returns the number of files successfully written.
    """
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    ok = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(
            storage_state=str(auth_path),
            user_agent=_USER_AGENT,
        )

        for att in attachments:
            dest = output_dir / att.filename
            if dest.exists():
                print(f"  skip  {att.filename} (already exists)")
                continue
            print(f"  dl    {att.filename} ...", end="", flush=True)
            try:
                resp = context.request.get(
                    att.url, headers={"Referer": "https://grok.com/"}
                )
                if not resp.ok:
                    print(f" FAILED: HTTP {resp.status}")
                    continue
                dest.write_bytes(resp.body())
                print(f" {dest.stat().st_size:,} bytes")
                ok += 1
            except Exception as exc:
                print(f" FAILED: {exc}")

        context.close()
        browser.close()

    return ok
