"""Configuration dataclasses for session, export, and environment settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class SessionCheck:
    """Result of a lightweight browser-based login/session check."""

    logged_in: bool
    url: str
    reason: str


@dataclass
class GrokSessionConfig:
    """Runtime configuration for browser automation and stored auth state."""

    grok_home: str = "https://grok.com/"
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
    locale: str = "en-US"
    timezone_id: str = "Europe/Paris"
    color_scheme: Literal["light", "dark", "no-preference", "null"] = "light"
    storage_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("GROKKO_STORAGE_DIR", Path.home() / ".grokko")
        ).expanduser()
    )
    viewport: dict[str, int] = field(
        default_factory=lambda: {"width": 1440, "height": 900}
    )

    @property
    def profile_dir(self) -> Path:
        """Return the local Playwright profile directory used by grokko."""
        return self.storage_dir / ".grok_profile"

    @property
    def state_file(self) -> Path:
        """Return the JSON file that stores captured browser cookies."""
        return self.storage_dir / "auth.json"

    def ensure_storage_dir(self) -> None:
        """Create the storage directory if it does not already exist."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SystemExit(
                f"error: Cannot create storage directory "
                f"{self.storage_dir}: {exc.strerror}"
            ) from exc


@dataclass
class GrokExportConfig:
    """Configuration for locating Grok export emails over IMAP."""

    imap_host: str = field(
        default_factory=lambda: os.environ.get("IMAP_HOST", "imap.gmail.com")
    )
    imap_port: int = field(
        default_factory=lambda: int(os.environ.get("IMAP_PORT", "993"))
    )
    imap_user: str = field(default_factory=lambda: os.environ.get("IMAP_USER", ""))
    imap_password: str = field(
        default_factory=lambda: os.environ.get("IMAP_PASSWORD", "")
    )
    subject: str = field(
        default_factory=lambda: os.environ.get(
            "GROK_EXPORT_SUBJECT", "Your data export is ready"
        )
    )
    sender: str | None = field(
        default_factory=lambda: os.environ.get("GROK_EXPORT_SENDER") or None
    )
    url_pattern: str = field(
        default_factory=lambda: os.environ.get(
            "GROK_EXPORT_URL_PATTERN",
            r"https://accounts\.x\.ai/download/\?file_reference=[\w/-]+\.zip",
        )
    )
    mailbox: str = field(
        default_factory=lambda: os.environ.get("GROK_EXPORT_MAILBOX", "INBOX")
    )
    poll_interval: int = field(
        default_factory=lambda: int(os.environ.get("GROK_EXPORT_POLL_INTERVAL", "30"))
    )
    poll_timeout: int = field(
        default_factory=lambda: int(os.environ.get("GROK_EXPORT_POLL_TIMEOUT", "600"))
    )

    def validate(self) -> None:
        """Ensure the IMAP credentials required for export polling are present."""
        missing = [
            name
            for name, val in (
                ("IMAP_USER", self.imap_user),
                ("IMAP_PASSWORD", self.imap_password),
            )
            if not val
        ]
        if missing:
            raise OSError(f"Missing required env vars: {', '.join(missing)}")
