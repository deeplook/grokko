"""IMAP polling helpers for Grok data-export notification emails."""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
import ssl
import sys
from datetime import datetime, timezone
from email.message import Message

from grokko.config import GrokExportConfig


def _imap_date(dt: datetime) -> str:
    """Format a datetime in the day-month-year style used by IMAP SEARCH."""
    return dt.strftime("%d-%b-%Y")


def _text_parts(msg: Message) -> list[str]:
    """Extract decoded plain-text and HTML message bodies from an email."""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                parts.append(payload.decode(charset, errors="replace"))
        return parts

    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        parts.append(payload.decode(charset, errors="replace"))
    return parts


def find_url_in_email(
    cfg: GrokExportConfig,
    after: datetime,
    verbose: bool = False,
) -> str | None:
    """Search recent export emails and return the first matching download URL."""
    since_str = _imap_date(after)
    criteria = f'(SINCE "{since_str}" SUBJECT "{cfg.subject}")'
    if cfg.sender:
        criteria = f'(SINCE "{since_str}" FROM "{cfg.sender}" SUBJECT "{cfg.subject}")'

    if verbose:
        print(
            f"[imap] Connecting to {cfg.imap_host}:{cfg.imap_port} "
            f"as {cfg.imap_user} ...",
            file=sys.stderr,
        )

    ctx = ssl.create_default_context()
    with imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, ssl_context=ctx) as imap:
        imap.login(cfg.imap_user, cfg.imap_password)
        imap.select(cfg.mailbox, readonly=True)

        if verbose:
            print(f"[imap] Searching: {criteria}", file=sys.stderr)
        status, data = imap.search(None, criteria)
        if status != "OK" or not data or not data[0]:
            return None

        msg_ids = data[0].split()
        if not msg_ids:
            return None

        if verbose:
            print(f"[imap] Found {len(msg_ids)} candidate message(s).", file=sys.stderr)

        after_aware = after if after.tzinfo else after.replace(tzinfo=timezone.utc)

        for msg_id in reversed(msg_ids):
            status, raw = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not raw or raw[0] is None:
                continue
            if not isinstance(raw[0], tuple):
                continue

            message_bytes = raw[0][1]
            if not isinstance(message_bytes, bytes):
                continue
            msg = email.message_from_bytes(message_bytes)

            date_str = msg.get("Date", "")
            if verbose:
                print(
                    f"[imap]   Date: {date_str}  Subject: {msg.get('Subject', '')!r}",
                    file=sys.stderr,
                )
            try:
                msg_dt = email.utils.parsedate_to_datetime(date_str)
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=timezone.utc)
                if msg_dt <= after_aware:
                    if verbose:
                        print(
                            f"[imap]   Skipping - not newer than {after_aware}",
                            file=sys.stderr,
                        )
                    continue
            except Exception:
                pass

            for text in _text_parts(msg):
                match = re.search(cfg.url_pattern, text)
                if match:
                    url = match.group(0)
                    if verbose:
                        print(f"[imap]   URL found: {url}", file=sys.stderr)
                    return url

            if verbose:
                print("[imap]   Pattern not matched in this message.", file=sys.stderr)

    return None
