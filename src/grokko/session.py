"""Browser/session management for Grok auth and shared Playwright workflows."""

from __future__ import annotations

import importlib
import json
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    ViewportSize,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)

from grokko.config import GrokExportConfig, GrokSessionConfig, SessionCheck

# Locale variants for consent/onboarding popup buttons across browser locales.
_CONSENT_LABELS = (
    "Accept",
    "Accept all",
    "Accepter",
    "Aceptar",
    "Accetta",
    "Akzeptieren",
    "Alle akzeptieren",
    "Tout accepter",
    "I agree",
    "Ich stimme zu",
    "Continue",
    "Weiter",
    "Continuer",
    "Got it",
    "Verstanden",
    "Close",
    "Maybe later",
)


class GrokSessionManager:
    """Manage saved browser state and shared Playwright-driven workflows."""

    def __init__(self, config: GrokSessionConfig | None = None):
        """Create a session manager backed by the configured storage directory."""
        self.config = config or GrokSessionConfig()
        self.config.ensure_storage_dir()

    def log(self, message: str) -> None:
        """Emit a standard log line prefixed for CLI output."""
        print(f"[grokko] {message}", file=sys.stderr)

    def looks_like_login_url(self, url: str) -> bool:
        """Return whether a URL appears to be part of an auth flow."""
        lowered = (url or "").lower()
        return any(
            token in lowered
            for token in (
                "grok.com/sign-in",
                "/sign-in",
                "/login",
                "x.com/i/flow/login",
                "twitter.com/i/flow/login",
                "oauth",
                "auth",
            )
        )

    def dismiss_common_popups(self, page: Page) -> None:
        """Best-effort dismissal of generic consent and onboarding popups."""
        for label in _CONSENT_LABELS:
            try:
                button = page.get_by_role("button", name=label).first
                if button.is_visible(timeout=400):
                    button.click(timeout=1000)
                    page.wait_for_timeout(150)
            except Exception:
                pass

    def check_session(self, page: Page) -> SessionCheck:
        """Inspect the current page for obvious signs of a logged-out session."""
        with suppress(Exception):
            page.wait_for_load_state("domcontentloaded", timeout=10000)

        self.dismiss_common_popups(page)
        url = page.url

        if self.looks_like_login_url(url):
            return SessionCheck(
                False, url, "Current URL still looks like an auth flow."
            )

        for text in (
            "Login with X",
            "Login with email",
            "Log into your account",
            "Don't have an account?",
            "Sign up",
        ):
            try:
                node = page.get_by_text(text, exact=False).first
                if node.is_visible(timeout=500):
                    return SessionCheck(
                        False, url, f"Signed-out text visible: {text!r}"
                    )
            except Exception:
                pass

        return SessionCheck(True, url, "No obvious sign-out markers detected.")

    def print_cookie_report(self, path: Path | None = None) -> None:
        """Print a human-readable report for the stored browser cookies."""
        state_path = path or self.config.state_file
        if not state_path.exists():
            self.log(f"No state file found at {state_path}")
            return

        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.log(f"Could not parse {state_path}: {exc}")
            return

        cookies = data.get("cookies", [])
        if not cookies:
            self.log("No cookies found in state file.")
            return

        now = datetime.now(timezone.utc)
        rows: list[tuple[str, str, str, float | None]] = []
        for cookie in cookies:
            name = cookie.get("name", "")
            domain = cookie.get("domain", "")
            expires = cookie.get("expires", -1)
            if isinstance(expires, int | float) and expires > 0:
                expires_at_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
                days_left_value = (expires_at_dt - now).total_seconds() / 86400
                rows.append((name, domain, expires_at_dt.isoformat(), days_left_value))
            else:
                rows.append((name, domain, "session/non-persistent", None))

        print("\nCookie report")
        print("-" * 95)
        for name, domain, expires_at_text, row_days_left in rows:
            if row_days_left is None:
                print(f"{name:<30} {domain:<30} {expires_at_text}")
            else:
                print(
                    f"{name:<30} {domain:<30} {expires_at_text} "
                    f"({row_days_left:.2f} days)"
                )
        print("-" * 95)

    def launch_persistent_context(
        self, playwright: Playwright, headless: bool
    ) -> BrowserContext:
        """Launch a persistent browser profile and hydrate it with saved cookies."""
        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        for lock_name in ("LOCK", "lockfile"):
            lock = self.config.profile_dir / "Default" / lock_name
            if lock.exists():
                lock.unlink()

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.profile_dir),
                headless=headless,
                channel="chrome",
                user_agent=self.config.user_agent,
                locale=self.config.locale,
                timezone_id=self.config.timezone_id,
                viewport=cast(ViewportSize, self.config.viewport),
                color_scheme=self.config.color_scheme,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc) or "chrome" in str(exc).lower():
                raise RuntimeError(
                    "Google Chrome not found. Install it from https://google.com/chrome"
                ) from exc
            raise
        if self.config.state_file.exists():
            self.log(f"Loading session from {self.config.state_file}")
            state = json.loads(self.config.state_file.read_text(encoding="utf-8"))
            cookies = state.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            """
        )
        return context

    def inspect(self) -> None:
        """Print the stored auth cookie report."""
        self.print_cookie_report(self.config.state_file)

    def _stealth_browser_context(
        self, playwright: Playwright, headless: bool
    ) -> tuple[Any, BrowserContext, Any]:
        """Create a non-persistent stealth browser context from saved auth state."""
        stealth_module = importlib.import_module("playwright_stealth")
        Stealth = stealth_module.Stealth

        _platform = {"darwin": "MacIntel", "win32": "Win32"}.get(
            sys.platform, "Linux x86_64"
        )
        stealth = Stealth(navigator_platform_override=_platform)
        try:
            browser = playwright.chromium.launch(
                headless=headless,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc) or "chrome" in str(exc).lower():
                raise RuntimeError(
                    "Google Chrome not found. Install it from https://google.com/chrome"
                ) from exc
            raise
        context = browser.new_context(
            storage_state=str(self.config.state_file),
            user_agent=self.config.user_agent,
            locale=self.config.locale,
            timezone_id=self.config.timezone_id,
            viewport=cast(ViewportSize, self.config.viewport),
            accept_downloads=True,
        )
        return browser, context, stealth

    def _goto_grok_home(self, page: Page) -> None:
        """Navigate a page to the configured Grok home URL."""
        page.goto(
            self.config.grok_home,
            wait_until="domcontentloaded",
            timeout=30000,
        )

    def request_data_export(self, headless: bool = False) -> bool:
        """Delegate the export-trigger flow to the dedicated export manager."""
        from grokko.export import GrokExportManager

        return GrokExportManager(self).request_data_export(headless=headless)

    def download_export_file(
        self, url: str, dest: Path | None = None, headless: bool = False
    ) -> Path | None:
        """Delegate export downloading to the dedicated export manager."""
        from grokko.export import GrokExportManager

        return GrokExportManager(self).download_export_file(
            url, dest=dest, headless=headless
        )

    def capture_from_chrome_cookies(self) -> bool:
        """Capture Grok-related cookies from the local Chrome profile."""
        try:
            import browser_cookie3
        except ImportError:
            self.log(
                "Failed to import 'browser-cookie3'. "
                "Re-install the package: uv tool install --reinstall ."
            )
            return False

        domains = {"grok.com", "x.ai", "x.com"}
        playwright_cookies: list[dict[str, object]] = []

        try:
            jar = browser_cookie3.chrome()
        except Exception as exc:
            self.log(f"Failed to read Chrome cookies: {exc}")
            return False

        for cookie in jar:
            host = cookie.domain.lstrip(".")
            if not any(domain in host for domain in domains):
                continue
            playwright_cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": int(cookie.expires) if cookie.expires else -1,
                    "httpOnly": False,
                    "secure": bool(cookie.secure),
                    "sameSite": "None",
                }
            )

        if not playwright_cookies:
            self.log("No cookies found for grok.com / x.ai in Chrome.")
            self.log("Make sure you are logged in to grok.com in Chrome first.")
            return False

        state = {"cookies": playwright_cookies, "origins": []}
        self.config.state_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.log(f"Saved {len(playwright_cookies)} cookies to {self.config.state_file}")
        return True

    def inspect_zip(self, zip_path: Path) -> bool:
        """Delegate ZIP inspection to the dedicated export manager."""
        from grokko.export import GrokExportManager

        return GrokExportManager(self).inspect_zip(zip_path)

    def ping(self, headless: bool = True) -> bool:
        """Check whether the saved session still appears to be logged in."""
        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            self._goto_grok_home(page)
            self.dismiss_common_popups(page)
            status = self.check_session(page)
            self.log(f"ping: logged_in={status.logged_in} url={status.url}")
            context.close()
            return status.logged_in

    def poll_for_export_url(
        self,
        after: datetime,
        export_config: GrokExportConfig | None = None,
        verbose: bool = False,
    ) -> str | None:
        """Delegate IMAP polling to the dedicated export manager."""
        from grokko.export import GrokExportManager

        return GrokExportManager(self).poll_for_export_url(
            after, export_config=export_config, verbose=verbose
        )

    def export_and_download(
        self,
        export_config: GrokExportConfig | None = None,
        dest: Path | None = None,
        headless: bool = False,
        verbose: bool = False,
    ) -> Path | None:
        """Delegate the end-to-end export flow to the dedicated export manager."""
        from grokko.export import GrokExportManager

        return GrokExportManager(self).export_and_download(
            export_config=export_config,
            dest=dest,
            headless=headless,
            verbose=verbose,
        )
