"""
Browser lifecycle management with Playwright + stealth.

Handles launching, configuring, and tearing down the browser, as well as
cookie-based session persistence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from cloakbrowser import launch


from src.config import BotConfig

logger = logging.getLogger(__name__)

# Realistic Chrome UA – keep reasonably up-to-date
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BrowserManager:
    """
    Manages a single Playwright browser instance with stealth patches.

    Usage::

        with BrowserManager(config) as bm:
            page = bm.page
            page.goto("https://omakase.in")
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── Properties ───────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError(
                "Browser not started – use 'with BrowserManager(cfg) as bm:'")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not started")
        return self._context

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> Page:
        """Launch the browser, apply stealth, and return the page."""
        logger.info("Launching browser (headless=%s)…", self.config.headless)

        self._pw = None
        launch_args = {
            "headless": self.config.headless,
            "humanize": True,
            "geoip": True,
            "locale": "en-US",
        }
        if getattr(self.config, "proxy", None):
            launch_args["proxy"] = {"server": self.config.proxy}
            logger.info("Using proxy: %s", self.config.proxy)
            
        self._browser = launch(**launch_args)
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        self._page = self._context.new_page()

        # Block heavy assets to save proxy bandwidth
        self._page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ["image", "media", "font"]
            else route.continue_()
        )

        logger.info("Browser ready")
        return self._page

    def stop(self) -> None:
        """Tear down browser resources gracefully."""
        for resource, name in [
            (self._page, "page"),
            (self._context, "context"),
            (self._browser, "browser"),
            (self._pw, "playwright"),
        ]:
            if resource is None:
                continue
            try:
                resource.close()  # type: ignore[union-attr]
            except Exception:
                logger.debug("Error closing %s (ignored)", name, exc_info=True)

        self._page = self._context = self._browser = self._pw = None
        logger.info("Browser closed")

    # ── Context manager ──────────────────────────────────────────────

    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ── Cookie persistence ───────────────────────────────────────────

    def save_cookies(self, path: Optional[Path] = None) -> None:
        """Persist browser cookies to disk."""
        dest = path or self.config.session_path
        cookies = self.context.cookies()
        dest.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        logger.info("Session saved → %s (%d cookies)", dest, len(cookies))

    def load_cookies(self, path: Optional[Path] = None) -> bool:
        """
        Restore cookies from a previous session.

        Returns True if cookies were loaded, False if the file was missing
        or corrupt.
        """
        src = path or self.config.session_path
        if not src.exists():
            logger.debug("No saved session at %s", src)
            return False

        if time.time() - src.stat().st_mtime > 30 * 60:
            logger.warning(
                "Saved session at %s is older than 30 minutes – ignoring", src)
            return False

        try:
            cookies = json.loads(src.read_text(encoding="utf-8"))
            self.context.add_cookies(cookies)
            logger.info("Restored %d cookies from %s", len(cookies), src)
            return True
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "Corrupt session file (%s) – ignoring: %s", src, exc)
            return False

    # ── Debug helpers ────────────────────────────────────────────────

    def screenshot(self, label: str = "debug") -> Path:
        """Take a timestamped screenshot and return its path."""
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.config.project_root / f"debug_{label}_{ts}.png"
        self.page.screenshot(path=str(dest))
        logger.info("Screenshot saved → %s", dest)
        return dest
