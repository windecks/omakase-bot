"""Authentication against omakase.in."""
from __future__ import annotations
import logging
from playwright.sync_api import Page
from src.browser import BrowserManager
from src.config import BotConfig, SESSION_EXPIRY_MINUTES
import time

logger = logging.getLogger(__name__)

def _is_logged_in(page: Page) -> bool:
    try:
        sel = (
            "a[href*='sign_out'], a[href*='logout'], "
            "a[href*='mypage'], a[href*='my_page'], "
            "a:has-text('Sign out'), a:has-text('Logout')"
        )
        page.locator(sel).first.wait_for(state="attached", timeout=5000)
        return True
    except: return False

def login(bm: BrowserManager, config: BotConfig) -> bool:
    if bm.load_cookies():
        bm.page.goto("https://omakase.in/en", wait_until="domcontentloaded")
        if _is_logged_in(bm.page):
            logger.info("✓ Session restored")
            return True
    return _do_login(bm, config)

def ensure_logged_in(bm: BrowserManager, config: BotConfig) -> bool:
    if bm.session_start_time and (time.time() - bm.session_start_time > SESSION_EXPIRY_MINUTES * 60):
        logger.warning("Active session is older than %d minutes. Forcing a refresh.", SESSION_EXPIRY_MINUTES)
        bm.context.clear_cookies()
        return _do_login(bm, config)
        
    return True if _is_logged_in(bm.page) else _do_login(bm, config)

def _do_login(bm: BrowserManager, config: BotConfig) -> bool:
    import time
    if config.is_login_locked():
        logger.info("Another task is currently logging in. Waiting for fresh cookies...")
        # Wait until the lock clears, up to ~60s
        for _ in range(60):
            if not config.is_login_locked():
                break
            time.sleep(1)
            
        # Lock cleared. Let's load the newly generated cookies!
        if bm.load_cookies():
            bm.page.goto("https://omakase.in/en", wait_until="domcontentloaded")
            if _is_logged_in(bm.page):
                logger.info("✓ Absorbed fresh session from other task!")
                return True
        logger.warning("Waited for login lock, but no fresh cookies found. Proceeding with UI login.")

    # We are the Leader. Lock other tasks out while we do the UI login.
    config.set_login_lock(60)

    page = bm.page
    logger.info("Navigating to login page...")
    page.goto("https://omakase.in/en/users/sign_in", wait_until="domcontentloaded")

    try: page.wait_for_load_state("networkidle", timeout=5000)
    except: pass

    if _is_logged_in(page):
        logger.info("✓ Redirected from login - already logged in")
        bm.save_cookies()
        config.set_login_lock(0)
        return True

    email_loc = page.locator("input[type='email'], input[name*='email']").first
    pass_loc = page.locator("input[type='password'], input[name*='password']").first
    submit_btn = page.locator("input[type='submit'], button:has-text('Log in'), button:has-text('Sign in')").first

    if not email_loc.is_visible(timeout=5000):
        logger.error("Could not find login form")
        bm.screenshot("login_failed")
        config.set_login_lock(0)
        return False

    email_loc.fill(config.email)
    pass_loc.fill(config.password)
    submit_btn.click()

    try: page.wait_for_load_state("networkidle", timeout=10000)
    except: pass

    if _is_logged_in(page):
        logger.info("✓ Login successful")
        bm.save_cookies()
        config.set_login_lock(0)
        return True
        
    logger.error("Login failed")
    config.set_login_lock(0)
    return False
