"""Data-export workflow helpers built on top of the shared session manager."""

from __future__ import annotations

import json
import time
import zipfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from grokko.config import GrokExportConfig
from grokko.imap import find_url_in_email
from grokko.session import GrokSessionManager


class GrokExportManager:
    """Trigger, poll, download, and inspect Grok account exports."""

    def __init__(self, session: GrokSessionManager) -> None:
        """Bind export workflows to an existing session manager."""
        self.session = session
        self.config = session.config

    def request_data_export(self, headless: bool = False) -> bool:
        """Open the account UI and trigger a new data export request."""
        if not self.config.state_file.exists():
            self.session.log("No auth.json found - run 'capture' first.")
            return False

        with sync_playwright() as playwright:
            browser, context, stealth = self.session._stealth_browser_context(
                playwright, headless=headless
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            self.session._goto_grok_home(page)
            self.session.dismiss_common_popups(page)
            page.wait_for_timeout(2000)

            profile_button = page.get_by_role("button", name="pfp")
            profile_button.wait_for(state="visible", timeout=10000)
            profile_button.click()
            self.session.log("Clicked profile button.")

            settings = (
                page.get_by_role("menuitem", name="Einstellungen")
                .or_(page.get_by_role("menuitem", name="Settings"))
                .first
            )
            settings.wait_for(state="visible", timeout=5000)
            settings.click()
            self.session.log("Opened settings dialog.")

            manage = page.locator(
                "button:has-text('Verwalten'), button:has-text('Manage')"
            ).first
            manage.wait_for(state="visible", timeout=5000)

            with context.expect_page(timeout=10000) as popup_info:
                manage.click()

            accounts_page = popup_info.value
            stealth.apply_stealth_sync(accounts_page)
            self.session.log(f"Popup: {accounts_page.url}")

            accounts_page.wait_for_load_state("domcontentloaded", timeout=15000)
            accounts_page.goto(
                "https://accounts.x.ai/data?redirect=grok-com&theme=light",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            ok = self._click_download_on_page(accounts_page)
            if not ok:
                self.session.log(
                    "Download button not found - check the browser window."
                )

            context.close()
            browser.close()
            return ok

    def download_export_file(
        self, url: str, dest: Path | None = None, headless: bool = False
    ) -> Path | None:
        """Download a known export URL through an authenticated browser session."""
        if not self.config.state_file.exists():
            self.session.log("No auth.json found - run 'capture' first.")
            return None

        with sync_playwright() as playwright:
            browser, context, stealth = self.session._stealth_browser_context(
                playwright, headless=headless
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            self.session._goto_grok_home(page)
            self.session.dismiss_common_popups(page)
            page.wait_for_timeout(1500)

            accounts_page = context.new_page()
            stealth.apply_stealth_sync(accounts_page)
            accounts_page.goto(
                "https://accounts.x.ai/account?redirect=grok-com&theme=light",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            accounts_page.wait_for_timeout(1000)

            self.session.log(f"Downloading: {url}")
            with accounts_page.expect_download(timeout=60000) as download_info:
                accounts_page.goto(url, wait_until="domcontentloaded", timeout=30000)

            download = download_info.value
            filename = download.suggested_filename or "grok-export.zip"
            output_path = dest or self.config.storage_dir / filename
            self.config.ensure_storage_dir()
            download.save_as(str(output_path))
            self.session.log(f"Saved to {output_path}")

            context.close()
            browser.close()
            return output_path

    def inspect_zip(self, zip_path: Path) -> bool:
        """Print a summary of the backend export archive contents."""
        if not zip_path.exists():
            self.session.log(f"File not found: {zip_path}")
            return False

        try:
            with zipfile.ZipFile(zip_path) as zip_file:
                backend = next(
                    (
                        name
                        for name in zip_file.namelist()
                        if name.endswith("prod-grok-backend.json")
                    ),
                    None,
                )
                if not backend:
                    self.session.log("No prod-grok-backend.json found in ZIP.")
                    return False

                data = json.loads(zip_file.read(backend))
        except Exception as exc:
            self.session.log(f"Could not read ZIP: {exc}")
            return False

        conversations = data.get("conversations", [])
        projects = data.get("projects", [])
        tasks = data.get("tasks", [])
        media_posts = data.get("media_posts", [])

        dates: list[datetime] = []
        for item in conversations:
            created_at = item.get("conversation", {}).get("create_time")
            if not created_at:
                continue
            with suppress(ValueError):
                dates.append(
                    datetime.fromisoformat(created_at.rstrip("Z")).replace(
                        tzinfo=timezone.utc
                    )
                )

        print(f"\nExport summary: {zip_path.name}")
        print("-" * 60)
        print(f"  Conversations : {len(conversations)}")
        print(f"  Projects      : {len(projects)}")
        print(f"  Media posts   : {len(media_posts)}")
        print(f"  Tasks         : {len(tasks)}")
        if dates:
            print(f"  Earliest      : {min(dates).strftime('%Y-%m-%d')}")
            print(f"  Latest        : {max(dates).strftime('%Y-%m-%d')}")
        print("-" * 60)
        return True

    def poll_for_export_url(
        self,
        after: datetime,
        export_config: GrokExportConfig | None = None,
        verbose: bool = False,
    ) -> str | None:
        """Poll IMAP until a fresh export email exposes a download URL."""
        cfg = export_config or GrokExportConfig()
        cfg.validate()

        deadline = time.time() + cfg.poll_timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            remaining = int(deadline - time.time())
            self.session.log(f"poll #{attempt} ({remaining}s remaining) ...")
            url = find_url_in_email(cfg, after, verbose=verbose)
            if url:
                self.session.log(f"URL found: {url}")
                return url
            if time.time() + cfg.poll_interval < deadline:
                time.sleep(cfg.poll_interval)
            else:
                break

        self.session.log("Timed out waiting for the download email.")
        return None

    def export_and_download(
        self,
        export_config: GrokExportConfig | None = None,
        dest: Path | None = None,
        headless: bool = False,
        verbose: bool = False,
    ) -> Path | None:
        """Trigger a data export, wait for the email, and download the archive."""
        cfg = export_config or GrokExportConfig()
        cfg.validate()

        now = datetime.now(timezone.utc)
        after = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.session.log(
            f"Triggering data export (looking for emails since {after.date()}) ..."
        )

        if not self.request_data_export(headless=headless):
            self.session.log("Could not trigger data export, aborting.")
            return None

        self.session.log(
            f"Export requested. Polling IMAP every {cfg.poll_interval}s "
            f"for up to {cfg.poll_timeout}s ..."
        )
        url = self.poll_for_export_url(after, export_config=cfg, verbose=verbose)
        if not url:
            return None

        return self.download_export_file(url, dest=dest, headless=headless)

    def _click_download_on_page(self, page: Page) -> bool:
        """Click the export download button on the current account/settings page."""
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        self.session.log(f"Landed on: {page.url}")

        button = page.locator(
            "button:has-text('Herunterladen'), button:has-text('Download')"
        ).first
        try:
            button.wait_for(state="visible", timeout=10000)
        except Exception:
            self.session.log("Download button not found.")
            return False

        self.session.log(f"Clicking: {button.inner_text().strip()!r}")
        button.click()
        page.wait_for_timeout(3000)
        self.session.log(
            "Data export requested - check your email for the download link."
        )
        return True
