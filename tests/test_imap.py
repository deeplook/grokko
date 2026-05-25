from __future__ import annotations

import imaplib
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import patch

from grokko import imap
from grokko.config import GrokExportConfig


def test_imap_date_and_text_parts_handle_single_and_multipart_messages() -> None:
    single = EmailMessage()
    single.set_content("hello")

    multi = EmailMessage()
    multi.set_content("plain")
    multi.add_alternative("<p>html</p>", subtype="html")

    assert imap._imap_date(datetime(2026, 5, 4)) == "04-May-2026"
    assert imap._text_parts(single) == ["hello\n"]
    assert imap._text_parts(multi) == ["plain\n", "<p>html</p>\n"]


def test_find_url_in_email_returns_matching_recent_url() -> None:
    older = EmailMessage()
    older["Date"] = "Sat, 03 May 2026 00:00:00 +0000"
    older["Subject"] = "Your data export is ready"
    older.set_content("https://accounts.x.ai/download/?file_reference=old.zip")

    newer = EmailMessage()
    newer["Date"] = "Sun, 04 May 2026 12:00:00 +0000"
    newer["Subject"] = "Your data export is ready"
    newer.set_content("https://accounts.x.ai/download/?file_reference=new.zip")

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            self.search_criteria: str | None = None

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            self.search_criteria = criteria
            return ("OK", [b"1 2"])

        def fetch(
            self, msg_id: bytes, spec: str
        ) -> tuple[str, list[tuple[bytes, bytes]]]:
            payload = older.as_bytes() if msg_id == b"1" else newer.as_bytes()
            return ("OK", [(b"RFC822", payload)])

    captured_fake: FakeImap | None = None

    def fake_factory(host: str, port: int, ssl_context: object) -> FakeImap:
        nonlocal captured_fake
        captured_fake = FakeImap(host, port, ssl_context)
        return captured_fake

    cfg = GrokExportConfig(
        imap_user="user@example.com",
        imap_password="secret",
        sender="exports@example.com",
    )
    after = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)

    with patch.object(imaplib, "IMAP4_SSL", fake_factory):
        url = imap.find_url_in_email(cfg, after, verbose=True)

    assert url == "https://accounts.x.ai/download/?file_reference=new.zip"
    assert captured_fake is not None
    criteria = captured_fake.search_criteria
    assert criteria is not None
    assert 'FROM "exports@example.com"' in criteria


def test_find_url_in_email_returns_none_when_search_is_empty() -> None:
    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b""])

    cfg = GrokExportConfig(imap_user="user@example.com", imap_password="secret")

    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        assert (
            imap.find_url_in_email(
                cfg, datetime(2026, 5, 4, tzinfo=timezone.utc), verbose=False
            )
            is None
        )


def test_find_url_in_email_returns_none_when_search_status_not_ok() -> None:
    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("NO", [b""])

    cfg = GrokExportConfig(imap_user="user@example.com", imap_password="secret")
    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(cfg, datetime(2026, 5, 4, tzinfo=timezone.utc))
    assert result is None


def test_find_url_in_email_no_sender_uses_simple_criteria() -> None:
    """When cfg.sender is empty the criteria omits FROM."""

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            self.criteria: str | None = None

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            self.criteria = criteria
            return ("OK", [b""])

    captured_fake: FakeImap | None = None

    def factory(host: str, port: int, ssl_context: object) -> FakeImap:
        nonlocal captured_fake
        captured_fake = FakeImap(host, port, ssl_context)
        return captured_fake

    cfg = GrokExportConfig(imap_user="u@e.com", imap_password="p", sender="")
    with patch.object(imaplib, "IMAP4_SSL", factory):
        imap.find_url_in_email(cfg, datetime(2026, 5, 4, tzinfo=timezone.utc))

    assert captured_fake is not None
    assert "FROM" not in (captured_fake.criteria or "")


def test_find_url_in_email_skips_bad_fetch_raw() -> None:
    """Messages where fetch returns None raw[0] are skipped."""

    good = EmailMessage()
    good["Date"] = "Mon, 05 May 2026 12:00:00 +0000"
    good["Subject"] = "export"
    good.set_content("https://accounts.x.ai/download/?file_reference=good.zip")

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b"1 2"])

        def fetch(self, msg_id: bytes, spec: str) -> tuple[str, list[object]]:
            if msg_id == b"1":
                return ("OK", [None])
            return ("OK", [(b"RFC822", good.as_bytes())])

    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(
            GrokExportConfig(imap_user="u@e.com", imap_password="p"),
            datetime(2026, 5, 4, tzinfo=timezone.utc),
        )

    assert result == "https://accounts.x.ai/download/?file_reference=good.zip"


def test_find_url_in_email_skips_non_tuple_raw() -> None:
    """Messages where raw[0] is not a tuple are skipped gracefully."""

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b"1"])

        def fetch(self, msg_id: bytes, spec: str) -> tuple[str, list[object]]:
            return ("OK", [b"not-a-tuple"])

    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(
            GrokExportConfig(imap_user="u@e.com", imap_password="p"),
            datetime(2026, 5, 4, tzinfo=timezone.utc),
        )

    assert result is None


def test_find_url_in_email_skips_message_with_no_url_match() -> None:
    """A valid email that does not contain the URL pattern is skipped."""

    no_url = EmailMessage()
    no_url["Date"] = "Mon, 05 May 2026 12:00:00 +0000"
    no_url["Subject"] = "export"
    no_url.set_content("No download link here, sorry.")

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b"1"])

        def fetch(self, msg_id: bytes, spec: str) -> tuple[str, list[object]]:
            return ("OK", [(b"RFC822", no_url.as_bytes())])

    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(
            GrokExportConfig(imap_user="u@e.com", imap_password="p"),
            datetime(2026, 5, 4, tzinfo=timezone.utc),
            verbose=True,
        )

    assert result is None


def test_find_url_in_email_skips_older_messages() -> None:
    """Emails whose date is not newer than `after` are skipped."""

    old_msg = EmailMessage()
    old_msg["Date"] = "Sat, 03 May 2026 00:00:00 +0000"
    old_msg["Subject"] = "export"
    old_msg.set_content("https://accounts.x.ai/download/?file_reference=old.zip")

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b"1"])

        def fetch(self, msg_id: bytes, spec: str) -> tuple[str, list[object]]:
            return ("OK", [(b"RFC822", old_msg.as_bytes())])

    after = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(
            GrokExportConfig(imap_user="u@e.com", imap_password="p"),
            after,
            verbose=True,
        )

    assert result is None


def test_find_url_in_email_naive_after_gets_utc() -> None:
    """A naive `after` datetime is treated as UTC."""

    msg = EmailMessage()
    msg["Date"] = "Mon, 05 May 2026 12:00:00 +0000"
    msg["Subject"] = "export"
    msg.set_content("https://accounts.x.ai/download/?file_reference=z.zip")

    class FakeImap:
        def __init__(self, host: str, port: int, ssl_context: object) -> None:
            pass

        def __enter__(self) -> FakeImap:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            return None

        def select(self, mailbox: str, readonly: bool = True) -> None:
            return None

        def search(self, charset: object, criteria: str) -> tuple[str, list[bytes]]:
            return ("OK", [b"1"])

        def fetch(self, msg_id: bytes, spec: str) -> tuple[str, list[object]]:
            return ("OK", [(b"RFC822", msg.as_bytes())])

    after_naive = datetime(2026, 5, 4, 0, 0)  # no tzinfo
    with patch.object(imaplib, "IMAP4_SSL", FakeImap):
        result = imap.find_url_in_email(
            GrokExportConfig(imap_user="u@e.com", imap_password="p"),
            after_naive,
        )

    assert result == "https://accounts.x.ai/download/?file_reference=z.zip"
