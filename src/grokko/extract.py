"""Convert Grok data export ZIPs into Obsidian-compatible Markdown notes."""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _parse_iso(s: str) -> datetime | None:
    """Parse an ISO timestamp string into a UTC datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_response_time(ct: object) -> datetime | None:
    """Parse both ISO strings and MongoDB $date.$numberLong (ms) timestamps."""
    if isinstance(ct, dict):
        try:
            ms = int(ct["$date"]["$numberLong"])
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        except (KeyError, ValueError, TypeError):
            return None
    if isinstance(ct, str):
        return _parse_iso(ct)
    return None


def _fmt_dt(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a datetime or return an empty string when missing."""
    return dt.strftime(fmt) if dt else ""


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r"[\s_]+")
_ASSET_PATH_RE = re.compile(r"/prod-mc-asset-server//([0-9a-f-]+)/content$")
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_GROK_RENDER_RE = re.compile(r"<grok:render\b[^>]*>.*?</grok:render>", re.DOTALL)


def _slugify(title: str, max_len: int = 60) -> str:
    """Convert a title into a filesystem-safe slug."""
    s = _UNSAFE_CHARS.sub("", title)
    s = _MULTI_SPACE.sub("-", s.strip())
    s = s.strip("-")
    return s[:max_len].rstrip("-") or "untitled"


def _note_filename(conv: dict[str, Any]) -> str:
    """Build the Markdown filename for a conversation."""
    title = conv.get("title") or "untitled"
    ct = _parse_iso(conv.get("create_time", ""))
    prefix = ct.strftime("%Y-%m-%d") if ct else "0000-00-00"
    return f"{prefix} {_slugify(title)}.md"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_SENDER_LABEL = {
    "human": "User",
    "assistant": "Grok",
}

_ATTACHMENT_MODES = {"files", "edited-images", "generated-images"}


def parse_attachment_modes(value: str) -> set[str]:
    """Parse the attachment mode CLI option into a normalized set."""
    raw_items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not raw_items:
        return set()
    if "all" in raw_items:
        return set(_ATTACHMENT_MODES)
    if "none" in raw_items:
        return set()

    invalid = [item for item in raw_items if item not in _ATTACHMENT_MODES]
    if invalid:
        valid = ", ".join(["none", "all", *_ATTACHMENT_MODES])
        raise ValueError(
            f"Invalid attachment mode(s): {', '.join(invalid)}. Choose from: {valid}"
        )

    return set(raw_items)


def _asset_index(zf: zipfile.ZipFile) -> dict[str, str]:
    """Index asset UUIDs to their ZIP member paths."""
    index: dict[str, str] = {}
    for name in zf.namelist():
        match = _ASSET_PATH_RE.search(name)
        if match:
            index[match.group(1)] = name
    return index


def _guess_extension(data: bytes) -> str:
    """Infer a file extension from content bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith(b"PK\x03\x04"):
        return ".zip"

    sample = data[:2048]
    if not sample:
        return ".bin"
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return ".bin"

    printable = sum(ch.isprintable() or ch.isspace() for ch in text)
    if printable / max(len(text), 1) > 0.95:
        return ".txt"
    return ".bin"


def _is_image_ext(ext: str) -> bool:
    """Return whether a file extension should be treated as an image."""
    return ext.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _clean_message_text(message: str) -> str:
    """Remove Grok-specific inline render markup from message text."""
    return _GROK_RENDER_RE.sub("", message).strip()


def _collect_web_resources(responses: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Collect unique cited or searched web resources from conversation responses."""
    resources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        source_resources = resp.get("cited_web_search_results") or resp.get(
            "web_search_results", []
        )
        for resource in source_resources:
            title = (resource.get("title") or "").strip()
            url = (resource.get("URL") or resource.get("url") or "").strip()
            if not title or not url:
                continue

            key = (title, url)
            if key in seen:
                continue

            seen.add(key)
            resources.append({"title": title, "url": url})

        for raw_card in resp.get("card_attachments_json", []):
            try:
                card = json.loads(raw_card)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            if card.get("cardType") != "citation_card":
                continue

            url = (card.get("url") or "").strip()
            if not url:
                continue

            title = (card.get("title") or url).strip()
            key = (title, url)
            if key in seen:
                continue

            seen.add(key)
            resources.append({"title": title, "url": url})

    return resources


def _collect_media_types(
    conv: dict[str, Any], responses: list[dict[str, Any]]
) -> list[str]:
    """Collect unique media types from the conversation and its responses."""
    media_types: list[str] = []

    for media_type in conv.get("media_types", []):
        if media_type and media_type not in media_types:
            media_types.append(media_type)

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        for media_type in cast(list[str], resp.get("media_types", [])):
            if media_type and media_type not in media_types:
                media_types.append(media_type)

    return media_types


def _collect_share_links(responses: list[dict[str, Any]]) -> list[str]:
    """Collect unique public share links from responses."""
    links: list[str] = []
    seen: set[str] = set()

    for item in responses:
        share_link = cast(dict[str, Any], item.get("share_link") or {})
        share_id = (share_link.get("share_link_id") or "").strip()
        if not share_id:
            continue

        url = f"https://grok.com/share/{share_id}"
        if url in seen:
            continue

        seen.add(url)
        links.append(url)

    return links


def _collect_webpage_urls(responses: list[dict[str, Any]]) -> list[str]:
    """Collect unique webpage URLs attached to responses."""
    urls: list[str] = []
    seen: set[str] = set()

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        for url in cast(list[str], resp.get("webpage_urls", [])):
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)

    return urls


def _collect_xpost_urls(responses: list[dict[str, Any]]) -> list[str]:
    """Collect unique X post URLs from response-level IDs."""
    urls: list[str] = []
    seen: set[str] = set()

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        for post_id in cast(list[str], resp.get("xpost_ids", [])):
            post_id = (post_id or "").strip()
            if not post_id:
                continue
            url = f"https://x.com/i/web/status/{post_id}"
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)

    return urls


def _collect_queries(responses: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Collect unique query strings and query types."""
    queries: list[str] = []
    query_types: list[str] = []
    seen_queries: set[str] = set()
    seen_query_types: set[str] = set()

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        query = (resp.get("query") or "").strip()
        query_type = (resp.get("query_type") or "").strip()

        if query and query not in seen_queries:
            seen_queries.add(query)
            queries.append(query)
        if query_type and query_type not in seen_query_types:
            seen_query_types.add(query_type)
            query_types.append(query_type)

    return queries, query_types


def _collect_generated_image_urls(responses: list[dict[str, Any]]) -> list[str]:
    """Collect unique generated image URL/path references."""
    urls: list[str] = []
    seen: set[str] = set()

    for item in responses:
        resp = cast(dict[str, Any], item.get("response", {}))
        for url in cast(list[str], resp.get("generated_image_urls", [])):
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)

    return urls


def _collect_image_edit_uris(responses: list[dict[str, Any]]) -> list[str]:
    """Collect unique image edit URI references."""
    uris: list[str] = []
    seen: set[str] = set()

    for item in responses:
        uri = (
            cast(dict[str, Any], item.get("response", {})).get("image_edit_uri") or ""
        ).strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        uris.append(uri)

    return uris


def _extract_attachments(
    conv_item: dict[str, Any],
    zf: zipfile.ZipFile,
    asset_paths: dict[str, str],
    note_path: Path,
    attachments_root: Path | None,
    attachment_modes: set[str],
) -> list[dict[str, str]]:
    """Extract configured attachment types for a conversation into files."""
    if not attachments_root or not attachment_modes:
        return []

    conv = cast(dict[str, Any], conv_item.get("conversation", {}))
    responses = cast(list[dict[str, Any]], conv_item.get("responses", []))
    conv_id = conv.get("id") or note_path.stem
    target_dir = attachments_root / conv_id

    candidates: list[tuple[datetime, str, str]] = []
    seen_assets: set[str] = set()

    for resp_item in responses:
        resp = resp_item.get("response", {})
        resp_dt = _parse_response_time(resp.get("create_time"))
        sort_dt = resp_dt or datetime.min.replace(tzinfo=timezone.utc)

        if "files" in attachment_modes:
            for asset_id in resp.get("file_attachments", []):
                if (
                    isinstance(asset_id, str)
                    and asset_id
                    and asset_id not in seen_assets
                ):
                    candidates.append((sort_dt, "file_attachments", asset_id))
                    seen_assets.add(asset_id)

        if "edited-images" in attachment_modes:
            image_edit_uri = resp.get("image_edit_uri") or ""
            match = _UUID_RE.search(image_edit_uri)
            if match and match.group(0) not in seen_assets:
                candidates.append((sort_dt, "image_edit_uri", match.group(0)))
                seen_assets.add(match.group(0))

        if "generated-images" in attachment_modes:
            for uri in resp.get("generated_image_urls", []):
                match = _UUID_RE.search(uri or "")
                if match and match.group(0) not in seen_assets:
                    candidates.append((sort_dt, "generated_image_urls", match.group(0)))
                    seen_assets.add(match.group(0))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    extracted: list[dict[str, str]] = []
    for index, (_, _, asset_id) in enumerate(candidates, start=1):
        asset_zip_path = asset_paths.get(asset_id)
        if not asset_zip_path:
            continue

        data = zf.read(asset_zip_path)
        ext = _guess_extension(data)
        filename = f"attachment-{index:02d}{ext}"
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / filename
        out_path.write_bytes(data)
        rel_path = out_path.relative_to(note_path.parent).as_posix()
        kind = "image" if _is_image_ext(ext) else "file"
        extracted.append(
            {
                "label": filename,
                "path": rel_path,
                "kind": kind,
            }
        )

    return extracted


def _render_note(
    conv_item: dict[str, Any],
    attachments: list[dict[str, str]] | None = None,
) -> str:
    """Render one conversation as a Markdown note."""
    conv = cast(dict[str, Any], conv_item.get("conversation", {}))
    responses = cast(list[dict[str, Any]], conv_item.get("responses", []))
    attachments = attachments or []

    title = conv.get("title") or "Untitled"
    created = _parse_iso(conv.get("create_time", ""))
    modified = _parse_iso(conv.get("modify_time", ""))
    conv_id = conv.get("id", "")
    starred = conv.get("starred", False)
    temporary = conv.get("temporary", False)
    system_prompt = (conv.get("system_prompt_name") or "").strip()
    summary = (conv.get("summary") or "").strip()
    web_resources = _collect_web_resources(responses)
    media_types = _collect_media_types(conv, responses)
    share_links = _collect_share_links(responses)
    webpage_urls = _collect_webpage_urls(responses)
    xpost_urls = _collect_xpost_urls(responses)
    queries, query_types = _collect_queries(responses)
    generated_image_urls = _collect_generated_image_urls(responses)
    image_edit_uris = _collect_image_edit_uris(responses)

    # Unique non-empty models, in order of first appearance
    models: list[str] = list(
        dict.fromkeys(
            r["response"].get("model", "")
            for r in responses
            if r["response"].get("model")
        )
    )

    # --- YAML frontmatter ---
    fm: list[str] = ["---"]
    fm.append(f"title: {json.dumps(title)}")
    if created:
        fm.append(f"created: {created.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if modified:
        fm.append(f"modified: {modified.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    fm.append(f"conversation_id: {conv_id}")
    if models:
        fm.append("models:")
        for m in models:
            fm.append(f"  - {m}")
    else:
        fm.append("models: []")
    fm.append(f"message_count: {len(responses)}")
    fm.append(f"web_resource_count: {len(web_resources)}")
    fm.append(f"attachment_count: {len(attachments)}")
    if len(attachments) == 1:
        fm.append(f"attachment_file: {json.dumps(attachments[0]['path'])}")
    elif attachments:
        fm.append("attachment_files:")
        for attachment in attachments:
            fm.append(f"  - {json.dumps(attachment['path'])}")
    if webpage_urls:
        fm.append(f"webpage_url_count: {len(webpage_urls)}")
    if xpost_urls:
        fm.append(f"xpost_count: {len(xpost_urls)}")
    if generated_image_urls:
        fm.append(f"generated_image_count: {len(generated_image_urls)}")
    if len(share_links) == 1:
        fm.append(f"share_link: {json.dumps(share_links[0])}")
    elif share_links:
        fm.append("share_links:")
        for link in share_links:
            fm.append(f"  - {json.dumps(link)}")
    if len(queries) == 1:
        fm.append(f"query: {json.dumps(queries[0])}")
    elif queries:
        fm.append("queries:")
        for query in queries:
            fm.append(f"  - {json.dumps(query)}")
    if len(query_types) == 1:
        fm.append(f"query_type: {query_types[0]}")
    elif query_types:
        fm.append("query_types:")
        for query_type in query_types:
            fm.append(f"  - {query_type}")
    if len(image_edit_uris) == 1:
        fm.append(f"image_edit_uri: {json.dumps(image_edit_uris[0])}")
    elif image_edit_uris:
        fm.append("image_edit_uris:")
        for uri in image_edit_uris:
            fm.append(f"  - {json.dumps(uri)}")
    if starred:
        fm.append("starred: true")
    if temporary:
        fm.append("temporary: true")
    if system_prompt:
        fm.append(f"system_prompt: {json.dumps(system_prompt)}")
    if len(media_types) == 1:
        fm.append(f"media_type: {media_types[0]}")
    elif media_types:
        fm.append("media_types:")
        for media_type in media_types:
            fm.append(f"  - {media_type}")
    fm.append("tags:")
    fm.append("  - grok")
    fm.append("---")
    fm.append("")

    # --- Title ---
    fm.append(f"# {title}")
    fm.append("")

    # --- Messages ---
    for r in responses:
        resp = r.get("response", {})
        sender_raw = resp.get("sender", "")
        label = _SENDER_LABEL.get(sender_raw, sender_raw.capitalize())
        model = resp.get("model", "")
        msg_dt = _parse_response_time(resp.get("create_time"))
        message = _clean_message_text(resp.get("message") or "")

        # Turn header: bold label · timestamp · model
        parts = [f"**{label}**"]
        if msg_dt:
            parts.append(_fmt_dt(msg_dt))
        if model:
            parts.append(f"*{model}*")

        fm.append(" · ".join(parts))
        fm.append("")
        if message:
            fm.append(message)
            fm.append("")
        fm.append("---")
        fm.append("")

    if web_resources:
        fm.append("<details>")
        fm.append("<summary>Web resources</summary>")
        fm.append("")
        if summary:
            fm.append(summary)
            fm.append("")
        for resource in web_resources:
            fm.append(f"- [{resource['title']}]({resource['url']})")
        fm.append("")
        fm.append("</details>")
        fm.append("")

    if webpage_urls:
        fm.append("<details>")
        fm.append("<summary>Referenced pages</summary>")
        fm.append("")
        for url in webpage_urls:
            fm.append(f"- [{url}]({url})")
        fm.append("")
        fm.append("</details>")
        fm.append("")

    if xpost_urls:
        fm.append("<details>")
        fm.append("<summary>X posts</summary>")
        fm.append("")
        for url in xpost_urls:
            fm.append(f"- [{url}]({url})")
        fm.append("")
        fm.append("</details>")
        fm.append("")

    if generated_image_urls or image_edit_uris:
        fm.append("<details>")
        fm.append("<summary>Image references</summary>")
        fm.append("")
        for url in generated_image_urls:
            fm.append(f"- Generated image: `{url}`")
        for uri in image_edit_uris:
            fm.append(f"- Image edit URI: `{uri}`")
        fm.append("")
        fm.append("</details>")
        fm.append("")

    if attachments:
        fm.append("<details>")
        fm.append("<summary>Attachments</summary>")
        fm.append("")
        for attachment in attachments:
            if attachment["kind"] == "image":
                fm.append(f"![]({attachment['path']})")
            else:
                fm.append(f"- [{attachment['label']}]({attachment['path']})")
        fm.append("")
        fm.append("</details>")
        fm.append("")

    return "\n".join(fm)


# ---------------------------------------------------------------------------
# Core export
# ---------------------------------------------------------------------------


def load_conversations(zip_path: Path) -> list[dict[str, Any]]:
    """Load all conversations from a Grok export ZIP."""
    with zipfile.ZipFile(zip_path) as zf:
        backend = next(
            (n for n in zf.namelist() if n.endswith("prod-grok-backend.json")), None
        )
        if not backend:
            raise FileNotFoundError("prod-grok-backend.json not found in ZIP")
        data = json.loads(zf.read(backend))
    return cast(list[dict[str, Any]], data.get("conversations", []))


def _sort_key(conv_item: dict[str, Any]) -> datetime:
    """Return the conversation creation timestamp used for sorting."""
    ct = cast(dict[str, Any], conv_item.get("conversation", {})).get("create_time", "")
    return _parse_iso(ct) or datetime.min.replace(tzinfo=timezone.utc)


class GrokExtractManager:
    """Convert Grok export ZIPs to Obsidian Markdown notes."""

    def __init__(self, zip_path: Path) -> None:
        """Initialize with the path to a Grok export ZIP."""
        self.zip_path = zip_path

    def export(
        self,
        output_dir: Path,
        limit: int | None = None,
        starred_only: bool = False,
        newest_first: bool = True,
        attachment_modes: set[str] | None = None,
        attachments_dir: Path | None = None,
    ) -> int:
        """
        Walk conversations in the export and write each as a Markdown note.
        Returns the number of files written.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        attachment_modes = attachment_modes or set()

        with zipfile.ZipFile(self.zip_path) as zf:
            backend = next(
                (n for n in zf.namelist() if n.endswith("prod-grok-backend.json")), None
            )
            if not backend:
                raise FileNotFoundError("prod-grok-backend.json not found in ZIP")
            data = json.loads(zf.read(backend))
            convs = data.get("conversations", [])

            convs.sort(key=_sort_key, reverse=newest_first)

            if starred_only:
                convs = [c for c in convs if c.get("conversation", {}).get("starred")]

            if limit is not None:
                convs = convs[:limit]

            seen: dict[str, int] = {}
            written = 0
            asset_paths = _asset_index(zf) if attachment_modes else {}
            resolved_attachments_dir: Path | None = None
            if attachment_modes:
                base_dir = attachments_dir or Path("_attachments")
                resolved_attachments_dir = (
                    base_dir if base_dir.is_absolute() else output_dir / base_dir
                )
                resolved_attachments_dir.mkdir(parents=True, exist_ok=True)

            for item in convs:
                conv = item.get("conversation", {})
                base_name = _note_filename(conv)

                # Resolve filename collisions
                if base_name in seen:
                    seen[base_name] += 1
                    stem = base_name[:-3]  # strip .md
                    out_path = output_dir / f"{stem} ({seen[base_name]}).md"
                else:
                    seen[base_name] = 0
                    out_path = output_dir / base_name

                attachments = _extract_attachments(
                    item,
                    zf,
                    asset_paths,
                    out_path,
                    resolved_attachments_dir,
                    attachment_modes,
                )
                content = _render_note(item, attachments=attachments)
                out_path.write_text(content, encoding="utf-8")
                written += 1
                print(f"  {out_path.name}")

        return written
