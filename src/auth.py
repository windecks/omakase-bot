"""
Authentication against omakase.in.

Handles login via the browser UI, session validation, and re-authentication.
"""

from __future__ import annotations

import logging
import time

from playwright.sync_api import Page, TimeoutError as PwTimeout

from src.browser import BrowserManager
from src.config import BotConfig

logger = logging.getLogger(__name__)

_LOGIN_URL = "https://omakase.in/en/login"

# Multiple selector strategies for resilience against DOM changes.
_EMAIL_SELECTORS = [
    "input[name='user[email]']",
    "input[type='email']",
    "input[placeholder*='mail' i]",
    "#user_email",
]
_PASSWORD_SELECTORS = [
    "input[name='user[password]']",
    "input[type='password']",
    "input[placeholder*='assword' i]",
    "#user_password",
]
_SUBMIT_SELECTORS = [
    "input[type='submit']",
    "button[type='submit']",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "input[value='Log in' i]",
]

# After login we look for any of these to confirm success.
_LOGGED_IN_INDICATORS = [
    "a[href*='logout']",
    "a[href*='sign_out']",
    "a:has-text('Logout')",
    "a:has-text('Sign out')",
    ".user-menu",
    "#user-menu",
    "a[href*='mypage']",
    "a[href*='my_page']",
    "a:has-text('My Page')",
    "a[href*='reservations']",
    "a[href*='favorites']",
    "a[href*='profile']",
    ".profile-icon",
]


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _find_element(page: Page, selectors: list[str], timeout: int = 5000):
    """Try each selector in order; return the first match or None."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                logger.debug("Matched selector: %s", sel)
                return el
        except PwTimeout:
            continue
    return None


def _is_logged_in(page: Page, timeout: int = 3000) -> bool:
    """Heuristic check: are we currently logged in?"""
    for sel in _LOGGED_IN_INDICATORS:
        try:
            if page.wait_for_selector(sel, timeout=timeout, state="attached"):
                return True
        except PwTimeout:
            continue
    return False


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def login(bm: BrowserManager, config: BotConfig) -> bool:
    """
    Perform a full login flow.

    1. Try restoring a saved session first.
    2. If that fails, navigate to the login page and authenticate.
    3. Save cookies on success.

    Returns True on success, False on failure.
    """
    page = bm.page

    # ── Attempt session restore ──────────────────────────────────────
    if bm.load_cookies():
        logger.info("Testing restored session…")
        page.goto("https://omakase.in/en", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass

        if _is_logged_in(page):
            logger.info("✓ Session restored – already logged in")
            return True
        logger.info("Saved session expired – performing fresh login")

    # ── Fresh login ──────────────────────────────────────────────────
    return _do_login(bm, config)


def ensure_logged_in(bm: BrowserManager, config: BotConfig) -> bool:
    """
    Check current login state and re-authenticate if needed.

    Useful for long-running monitor loops where sessions may expire.
    """
    if _is_logged_in(bm.page):
        return True

    logger.warning("Session expired – re-authenticating…")
    return _do_login(bm, config)


# ────────────────────────────────────────────────────────────────────────
# Internal
# ────────────────────────────────────────────────────────────────────────


def _do_login(bm: BrowserManager, config: BotConfig) -> bool:
    """Execute the login form flow."""
    page = bm.page

    logger.info("Navigating to homepage to find login link…")
    page.goto("https://omakase.in/en", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PwTimeout:
        pass
    time.sleep(0.5)

    # ── Click login link ─────────────────────────────────────────────
    login_link_selectors = [
        "a[href*='sign_in']",
        "a[href*='login']",
        "a:has-text('Login')",
        "a:has-text('Sign in')",
    ]
    login_link = _find_element(page, login_link_selectors, timeout=5000)
    if login_link:
        logger.info("Clicking login link…")
        login_link.click()
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass
        time.sleep(0.5)
    else:
        logger.warning(
            "Could not find a login link on the homepage. Assuming already on login page or relying on form fields appearing."
        )

    # ── Find form elements ───────────────────────────────────────────
    email_input = _find_element(page, _EMAIL_SELECTORS)
    if not email_input:
        logger.error("Could not find email input on login page")
        bm.screenshot("login_no_email")
        return False

    password_input = _find_element(page, _PASSWORD_SELECTORS)
    if not password_input:
        logger.error("Could not find password input on login page")
        bm.screenshot("login_no_password")
        return False

    submit_btn = _find_element(page, _SUBMIT_SELECTORS)
    if not submit_btn:
        logger.error("Could not find submit button on login page")
        bm.screenshot("login_no_submit")
        return False

    # ── Fill & submit ────────────────────────────────────────────────
    logger.info("Filling login form for %s…", config.email)
    email_input.fill(config.email)
    time.sleep(0.3)
    password_input.fill(config.password)
    time.sleep(0.3)

    logger.info("Submitting login form…")
    submit_btn.click()

    # Wait for navigation after submit
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PwTimeout:
        logger.warning("Network didn't settle after login submit – continuing anyway")

    time.sleep(1.0)

    # ── Verify success ───────────────────────────────────────────────
    if _is_logged_in(page):
        logger.info("✓ Login successful")
        bm.save_cookies()
        return True

    # Check for common error messages
    error_selectors = [
        ".alert-danger",
        ".flash-error",
        ".error-message",
        "[class*='error']",
        "[class*='alert']",
    ]
    for sel in error_selectors:
        try:
            el = page.wait_for_selector(sel, timeout=2000)
            if el:
                text = el.text_content() or ""
                if text.strip():
                    logger.error("Login error message: %s", text.strip())
                    break
        except PwTimeout:
            continue

    logger.error("Login failed – could not verify logged-in state")
    bm.screenshot("login_failed")
    return False
