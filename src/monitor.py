"""
Monitor mode – periodically check for cancellation slots.

Polls the restaurant page at a configurable interval and books
(or notifies) when an opening appears.
"""

from __future__ import annotations

import logging
import signal
import time
from types import FrameType
from typing import Optional

from src.auth import ensure_logged_in, login
from src.browser import BrowserManager
from src.config import BotConfig
from src.notifications import (
    notify_booking_failed,
    notify_booking_success,
    notify_slot_found,
    notify_waiting,
    notify_antibot,
)
from src.reservation import BookingResult, attempt_booking

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown_requested = False


def _handle_sigint(sig: int, frame: Optional[FrameType]) -> None:
    global _shutdown_requested
    if _shutdown_requested:
        logger.warning("Force quit")
        raise SystemExit(1)
    _shutdown_requested = True
    logger.info("\n⏹  Shutdown requested – finishing current check…")


def run_monitor(bm: BrowserManager, config: BotConfig) -> bool:
    """
    Execute monitor mode.

    Polls for availability every `check_interval` seconds.
    When a slot is found:
      - If auto_book=True: attempts to book immediately.
      - If auto_book=False: notifies and exits.

    Returns True if a booking was made (or a slot was found with auto_book=False).
    """
    global _shutdown_requested
    _shutdown_requested = False

    # Install signal handler for graceful Ctrl+C
    prev_handler = signal.signal(signal.SIGINT, _handle_sigint)

    page = bm.page

    # ── Login ────────────────────────────────────────────────────────
    logger.info("Monitor mode: logging in…")
    if not login(bm, config):
        logger.error("Login failed – cannot proceed")
        signal.signal(signal.SIGINT, prev_handler)
        return False

    check_number = 0

    try:
        while not _shutdown_requested:
            rem = config.get_account_lock_remaining()
            if rem > 0:
                logger.info("Account is currently locked by another task. Sleeping for %.0fs...", rem)
                _wait_interval(int(rem) + 5)
                continue
                
            check_number += 1
            logger.info("━━━ Check #%d ━━━", check_number)

            # Re-verify login periodically
            if check_number % 5 == 0:
                if not ensure_logged_in(bm, config):
                    logger.error("Re-login failed")
                    return False

            try:
                result, found_time, url = attempt_booking(bm, config)
            except Exception as e:
                logger.error("Check #%d crashed: %s", check_number, e)
                bm.screenshot(f"monitor_crash_{check_number}")
                _wait_interval(config.check_interval)
                continue

            if result == BookingResult.SUCCESS and found_time:
                # Slot found! Set lock to silence other tasks on this account for 5 mins
                config.set_account_lock(5)
                if not config.auto_book:
                    notify_slot_found(config.date, found_time, config.restaurant_id, url, config.discord_webhook_url, config.discord_user_id)
                    logger.info(
                        "Manual hold successful – exiting with notification only")
                    return True
                else:
                    notify_booking_success(
                        config.date, found_time, config.restaurant_id, url, config.discord_webhook_url, config.discord_user_id)
                    bm.screenshot("monitor_success")
                    return True

            elif result == BookingResult.ALREADY_BOOKED:
                logger.warning("Account is holding another reservation. Setting lock for 5 minutes.")
                config.set_account_lock(5)
                continue
            elif result == BookingResult.ANTIBOT_TRIGGERED:
                logger.error("Anti-bot triggered on monitor cycle.")
                notify_antibot(config.restaurant_id, config.discord_webhook_url, config.discord_user_id)
                # Lock account for 15 minutes to cool down
                config.set_account_lock(15)
                continue
            elif result == BookingResult.DATE_UNAVAILABLE:
                logger.info(
                    "Date %s not yet available on calendar", config.date)
            elif result == BookingResult.NO_SLOTS:
                logger.info("No slots available for %s", config.date)
            else:
                logger.info("Check result: %s", result.value)

            # Wait before next check
            if not _shutdown_requested:
                _wait_interval(config.check_interval)

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, prev_handler)

    logger.info("Monitor stopped (checked %d times)", check_number)
    return False


def _wait_interval(seconds: int) -> None:
    """Sleep in 1-second increments so we can respond to shutdown quickly."""
    global _shutdown_requested

    notify_waiting(f"Next check in {seconds}s…")

    for _ in range(seconds):
        if _shutdown_requested:
            return
        time.sleep(1)
