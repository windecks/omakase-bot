"""
Sniper mode – book a slot the instant it drops.

Waits until the configured release time, then rapidly refreshes
and attempts to grab the target slot.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from src.auth import ensure_logged_in, login
from src.browser import BrowserManager
from src.config import BotConfig
from src.notifications import (
    notify_booking_failed,
    notify_booking_success,
    notify_slot_found,
    notify_waiting,
)
from src.reservation import BookingResult, attempt_booking, quick_refresh_and_book

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _parse_release_time(release_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    h, m = release_str.split(":")
    return int(h), int(m)


def _wait_until_release(release_hour: int, release_minute: int) -> None:
    """
    Block until the release time in JST.

    Starts waking up ~5 seconds early to account for clock drift and
    network latency.
    """
    now = datetime.now(JST)
    release = now.replace(hour=release_hour, minute=release_minute, second=0, microsecond=0)

    # If release time has already passed today, wait for tomorrow
    if now >= release:
        release += timedelta(days=1)

    wait_seconds = (release - now).total_seconds()

    # Wake up 5 seconds early
    early_wake = max(0, wait_seconds - 5)

    logger.info(
        "Release time: %s JST (in %.0f seconds)",
        release.strftime("%Y-%m-%d %H:%M:%S"),
        wait_seconds,
    )

    if early_wake > 60:
        notify_waiting(f"Sleeping until ~{release.strftime('%H:%M')} JST ({early_wake / 60:.0f} min)…")

        # Sleep in chunks so we can show progress
        remaining = early_wake
        while remaining > 60:
            sleep_chunk = min(remaining - 30, 300)  # wake every 5 min max
            time.sleep(sleep_chunk)
            remaining -= sleep_chunk
            now = datetime.now(JST)
            to_go = (release - now).total_seconds()
            if to_go > 0:
                notify_waiting(f"{to_go:.0f}s until release…")

    # Final precision wait
    now = datetime.now(JST)
    final_wait = (release - now).total_seconds() - 2  # 2 seconds early
    if final_wait > 0:
        time.sleep(final_wait)

    # Busy-wait the last 2 seconds for precision
    while datetime.now(JST) < release:
        time.sleep(0.05)

    logger.info("🚀 Release time reached – GO GO GO!")


def run_sniper(bm: BrowserManager, config: BotConfig) -> bool:
    """
    Execute sniper mode.

    1. Login and navigate to the restaurant page before release time.
    2. Wait for the exact release time.
    3. Rapidly refresh and attempt to book.

    Returns True if booking succeeded.
    """
    page = bm.page

    # ── Step 1: Pre-authenticate ─────────────────────────────────────
    logger.info("Sniper mode: pre-authenticating…")
    if not login(bm, config):
        logger.error("Login failed – cannot proceed")
        return False

    # ── Step 2: Pre-load reservation page ────────────────────────────
    logger.info("Pre-loading reservation page: %s", config.reservation_url)
    page.goto(config.reservation_url, wait_until="domcontentloaded")

    logger.info("Reservation page loaded. Waiting for release time…")

    # ── Step 3: Wait for release ─────────────────────────────────────
    release_h, release_m = _parse_release_time(config.release_time)
    _wait_until_release(release_h, release_m)

    # ── Step 4: Rapid booking attempts ───────────────────────────────
    for attempt in range(1, config.max_attempts + 1):
        if config.get_account_lock_remaining() > 0:
            logger.info("Account is currently locked by another task. Sniper aborting.")
            return False
            
        start = time.monotonic()

        logger.info("━━━ Attempt %d/%d ━━━", attempt, config.max_attempts)

        # Re-check login on every ~10th attempt
        if attempt % 10 == 0:
            if not ensure_logged_in(bm, config):
                logger.error("Re-login failed on attempt %d", attempt)
                return False

        try:
            if attempt == 1:
                result, booked_time, url = attempt_booking(bm, config)
            else:
                result, booked_time, url = quick_refresh_and_book(bm, config)
        except Exception as e:
            logger.error("Attempt %d crashed: %s", attempt, e)
            bm.screenshot(f"sniper_crash_{attempt}")
            time.sleep(0.5)
            continue

        elapsed = time.monotonic() - start
        logger.debug("Attempt %d took %.2fs → %s", attempt, elapsed, result.value)

        if result == BookingResult.SUCCESS:
            config.set_account_lock(5)
            if not config.auto_book:
                notify_slot_found(config.date, booked_time or config.time, config.restaurant_id, url, config.discord_webhook_url, config.discord_user_id)
                logger.info("Manual hold successful – exiting with notification only")
            else:
                notify_booking_success(config.date, booked_time or config.time, config.restaurant_id, url, config.discord_webhook_url, config.discord_user_id)
            bm.screenshot("sniper_success")
            return True

        if result == BookingResult.ALREADY_BOOKED:
            logger.warning("Account is holding a reservation for another restaurant. Sniper aborting.")
            config.set_account_lock(5)
            return False

        if result == BookingResult.BOOKING_FAILED:
            notify_booking_failed(f"Slot found but booking failed (attempt {attempt})")
            # Continue trying – might have been a race condition

        # Small jittered delay between attempts
        jitter = random.uniform(0.05, 0.2)
        time.sleep(jitter)

    notify_booking_failed(f"Exhausted all {config.max_attempts} attempts")
    bm.screenshot("sniper_exhausted")
    return False
