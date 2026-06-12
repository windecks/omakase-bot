"""
Core reservation logic.

Navigates the restaurant page, finds available dates/slots, and
completes the booking flow.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from enum import Enum
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PwTimeout

from src.browser import BrowserManager
from src.config import BotConfig

logger = logging.getLogger(__name__)

BASE_URL = "https://omakase.in"


class BookingResult(Enum):
    """Outcome of a booking attempt."""
    SUCCESS = "success"
    NO_SLOTS = "no_slots"
    DATE_UNAVAILABLE = "date_unavailable"
    BOOKING_FAILED = "booking_failed"
    ALREADY_BOOKED = "already_booked"


# ────────────────────────────────────────────────────────────────────────
# Human-like delays
# ────────────────────────────────────────────────────────────────────────

def _human_delay(low: float = 0.2, high: float = 0.8) -> None:
    """Sleep a random duration to mimic human pacing."""
    time.sleep(random.uniform(low, high))


def _find(page: Page, selectors: list[str], timeout: int = 5000):
    """Try each selector; return the first visible match or None."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                logger.debug("Matched selector: %s", sel)
                return el
        except PwTimeout:
            continue
    return None


# ────────────────────────────────────────────────────────────────────────
# Calendar navigation
# ────────────────────────────────────────────────────────────────────────

def _get_calendar_month_year(page: Page) -> Optional[tuple[int, int]]:
    """
    Extract the currently displayed month/year from the calendar header.

    Returns (year, month) or None if unreadable.
    """
    # Common calendar header selectors
    header_selectors = [
        ".calendar-header",
        ".datepicker-switch",
        ".flatpickr-current-month",
        ".fc-toolbar-title",
        "[class*='month-header']",
        "[class*='calendar'] [class*='title']",
        "[class*='calendar'] [class*='header']",
        "th.month",
        ".month-name",
    ]

    for sel in header_selectors:
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.text_content() or "").strip()
                if text:
                    return _parse_month_year(text)
        except Exception:
            continue

    # Fallback: look for any element with month names
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    for month_name in months:
        try:
            el = page.query_selector(f"text='{month_name}'")
            if el:
                text = (el.text_content() or "").strip()
                parsed = _parse_month_year(text)
                if parsed:
                    return parsed
        except Exception:
            continue

    return None


def _parse_month_year(text: str) -> Optional[tuple[int, int]]:
    """Parse strings like 'July 2026' or '2026年7月' into (year, month)."""
    import re

    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    text_lower = text.lower().strip()

    # "July 2026" / "Jul 2026"
    for name, num in month_names.items():
        if name[:3] in text_lower:
            year_match = re.search(r"20\d{2}", text)
            if year_match:
                return int(year_match.group()), num

    # "2026年7月" (Japanese format)
    jp_match = re.search(r"(\d{4})\D+(\d{1,2})", text)
    if jp_match:
        return int(jp_match.group(1)), int(jp_match.group(2))

    # "7/2026" or "07/2026"
    slash_match = re.search(r"(\d{1,2})/(\d{4})", text)
    if slash_match:
        return int(slash_match.group(2)), int(slash_match.group(1))

    return None


def _navigate_to_month(page: Page, target_year: int, target_month: int,
                       max_clicks: int = 24) -> bool:
    """
    Navigate the calendar forward/backward until we reach the target month.

    Returns True if successful, False if we can't navigate there.
    """
    next_selectors = [
        ".calendar-next",
        ".flatpickr-next-month",
        "button:has-text('›')",
        "button:has-text('>')",
        "button:has-text('Next')",
        "[class*='next']",
        "[aria-label='Next month']",
        ".next",
    ]
    prev_selectors = [
        ".calendar-prev",
        ".flatpickr-prev-month",
        "button:has-text('‹')",
        "button:has-text('<')",
        "button:has-text('Prev')",
        "[class*='prev']",
        "[aria-label='Previous month']",
        ".prev",
    ]

    for attempt in range(max_clicks):
        current = _get_calendar_month_year(page)
        if current is None:
            logger.warning("Cannot read current calendar month (attempt %d)", attempt + 1)
            _human_delay(0.5, 1.0)
            continue

        cur_year, cur_month = current
        logger.debug("Calendar showing: %d-%02d, target: %d-%02d",
                     cur_year, cur_month, target_year, target_month)

        if cur_year == target_year and cur_month == target_month:
            return True

        # Determine direction
        cur_total = cur_year * 12 + cur_month
        target_total = target_year * 12 + target_month

        if target_total > cur_total:
            btn = _find(page, next_selectors, timeout=3000)
            direction = "next"
        else:
            btn = _find(page, prev_selectors, timeout=3000)
            direction = "prev"

        if not btn:
            logger.error("Cannot find %s month button", direction)
            return False

        btn.click()
        _human_delay(0.3, 0.6)
        page.wait_for_load_state("networkidle")

    logger.error("Could not navigate to %d-%02d after %d clicks", target_year, target_month, max_clicks)
    return False


# ────────────────────────────────────────────────────────────────────────
# Date selection
# ────────────────────────────────────────────────────────────────────────

def _click_date(page: Page, target_day: int) -> bool:
    """
    Click a specific day number on the calendar.

    Returns True if we found and clicked it.
    """
    day_str = str(target_day)

    # Strategy 1: look for clickable date cells with the day number
    date_selectors = [
        f"td a:text-is('{day_str}')",
        f"td:text-is('{day_str}'):not(.disabled):not(.unavailable)",
        f"button:text-is('{day_str}')",
        f".day:text-is('{day_str}')",
        f"[data-day='{day_str}']",
        f"a:text-is('{day_str}')",
    ]

    for sel in date_selectors:
        try:
            locator = page.locator(sel)
            count = locator.count()
            if count > 0:
                # If multiple matches, try to find one that isn't disabled
                for i in range(count):
                    el = locator.nth(i)
                    classes = el.get_attribute("class") or ""
                    parent_classes = ""
                    try:
                        parent = el.locator("..")
                        parent_classes = parent.get_attribute("class") or ""
                    except Exception:
                        pass

                    all_classes = f"{classes} {parent_classes}".lower()
                    if "disabled" in all_classes or "unavailable" in all_classes or "past" in all_classes:
                        continue

                    logger.info("Clicking date %d with selector: %s", target_day, sel)
                    el.click()
                    return True
        except Exception:
            continue

    # Strategy 2: broader search for any element containing just the day number
    # within the calendar area
    calendar_containers = [
        ".calendar", "[class*='calendar']", ".datepicker",
        "[class*='datepicker']", "table",
    ]
    for container_sel in calendar_containers:
        try:
            container = page.query_selector(container_sel)
            if not container:
                continue
            # Find all clickable elements within the calendar
            links = container.query_selector_all("a, button, td[role='button'], div[role='button']")
            for link in links:
                text = (link.text_content() or "").strip()
                if text == day_str:
                    classes = (link.get_attribute("class") or "").lower()
                    if "disabled" not in classes and "unavailable" not in classes:
                        logger.info("Clicking date %d via container search", target_day)
                        link.click()
                        return True
        except Exception:
            continue

    logger.warning("Could not find clickable date %d on calendar", target_day)
    return False


# ────────────────────────────────────────────────────────────────────────
# Party size selection
# ────────────────────────────────────────────────────────────────────────

def _select_party_size(page: Page, party_size: int) -> bool:
    """
    Attempt to set the party size if there's a selector for it.

    Returns True if handled (or not needed), False on failure.
    """
    party_selectors = [
        "select[name*='party']",
        "select[name*='guest']",
        "select[name*='people']",
        "select[name*='pax']",
        "select[name*='seats']",
        "[class*='party-size'] select",
        "[class*='guest-count'] select",
    ]

    for sel in party_selectors:
        try:
            el = page.query_selector(sel)
            if el:
                logger.info("Setting party size to %d", party_size)
                el.select_option(value=str(party_size))
                _human_delay()
                return True
        except Exception:
            continue

    # Try button-based party size (+ / - buttons)
    try:
        current = page.query_selector("[class*='party'] [class*='count'], [class*='guest'] [class*='count']")
        if current:
            current_val = int((current.text_content() or "2").strip())
            diff = party_size - current_val
            btn_sel = "[class*='party'] [class*='plus'], [class*='guest'] [class*='increment']" if diff > 0 else \
                      "[class*='party'] [class*='minus'], [class*='guest'] [class*='decrement']"
            btn = page.query_selector(btn_sel)
            if btn:
                for _ in range(abs(diff)):
                    btn.click()
                    _human_delay(0.1, 0.3)
                return True
    except Exception:
        pass

    logger.debug("No party size selector found – may be pre-set or on next page")
    return True  # Not necessarily an error


# ────────────────────────────────────────────────────────────────────────
# Time slot selection
# ────────────────────────────────────────────────────────────────────────

def _find_time_slots(page: Page) -> list[tuple[str, any]]:
    """
    Discover available time slots on the page.

    Returns a list of (time_string, element) tuples.
    """
    import re

    slots: list[tuple[str, any]] = []

    # Common slot selectors
    slot_selectors = [
        "a[class*='slot']",
        "button[class*='slot']",
        "div[class*='slot']",
        "a[class*='time']",
        "button[class*='time']",
        ".available-slot",
        ".time-slot",
        "[data-time]",
        "[class*='booking'] a",
        "[class*='reservation'] a",
    ]

    for sel in slot_selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                text = (el.text_content() or "").strip()
                classes = (el.get_attribute("class") or "").lower()

                if "disabled" in classes or "unavailable" in classes or "sold" in classes:
                    continue

                # Extract time pattern (e.g., "18:00", "6:00 PM")
                time_match = re.search(r"(\d{1,2}:\d{2})", text)
                if time_match:
                    slots.append((time_match.group(1), el))
                elif el.get_attribute("data-time"):
                    slots.append((el.get_attribute("data-time"), el))
        except Exception:
            continue

    # Deduplicate by time string
    seen = set()
    unique_slots = []
    for time_str, el in slots:
        if time_str not in seen:
            seen.add(time_str)
            unique_slots.append((time_str, el))

    return unique_slots


def _pick_best_slot(slots: list[tuple[str, any]], preferred_time: str) -> Optional[tuple[str, any]]:
    """
    Pick the slot closest to the preferred time.

    Returns (time_string, element) or None if no slots.
    """
    if not slots:
        return None

    def _time_to_minutes(t: str) -> int:
        parts = t.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    target_mins = _time_to_minutes(preferred_time)

    best = None
    best_diff = float("inf")
    for time_str, el in slots:
        try:
            diff = abs(_time_to_minutes(time_str) - target_mins)
            if diff < best_diff:
                best_diff = diff
                best = (time_str, el)
        except (ValueError, IndexError):
            continue

    return best


# ────────────────────────────────────────────────────────────────────────
# Booking confirmation
# ────────────────────────────────────────────────────────────────────────

def _confirm_booking(page: Page, bm: BrowserManager) -> bool:
    """
    Complete the booking after selecting a time slot.

    This handles any confirmation pages/dialogs that appear.
    """
    _human_delay(0.5, 1.0)
    page.wait_for_load_state("networkidle")

    # Look for confirmation / submit / book buttons
    confirm_selectors = [
        "button:has-text('Confirm')",
        "button:has-text('confirm')",
        "button:has-text('Complete')",
        "button:has-text('Book')",
        "button:has-text('Reserve')",
        "button:has-text('Submit')",
        "input[type='submit']",
        "button[type='submit']",
        "a:has-text('Confirm')",
        "a:has-text('Complete')",
        "[class*='confirm'] button",
        "[class*='submit'] button",
    ]

    # There might be multiple confirmation steps
    for step in range(3):
        logger.debug("Confirmation step %d", step + 1)

        btn = _find(page, confirm_selectors, timeout=5000)
        if not btn:
            # Check if we're already on a success page
            if _is_booking_success(page):
                return True
            if step == 0:
                logger.warning("No confirmation button found – checking if booking went through")
                _human_delay(1.0, 2.0)
                if _is_booking_success(page):
                    return True
            break

        logger.info("Clicking confirmation button (step %d)…", step + 1)
        btn.click()
        _human_delay(0.5, 1.5)

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass

        if _is_booking_success(page):
            return True

    return _is_booking_success(page)


def _is_booking_success(page: Page) -> bool:
    """Check if the current page indicates a successful booking."""
    success_indicators = [
        "text='Reservation confirmed'",
        "text='Booking confirmed'",
        "text='reservation has been confirmed'",
        "text='Successfully reserved'",
        "text='Thank you'",
        "text='予約が確定しました'",
        "[class*='success']",
        "[class*='confirmed']",
        ".reservation-confirmed",
    ]

    for sel in success_indicators:
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.text_content() or "").strip()
                if text:
                    logger.info("Success indicator found: %s", text[:100])
                    return True
        except Exception:
            continue

    # Also check URL for success indicators
    url = page.url.lower()
    if any(kw in url for kw in ["confirm", "success", "complete", "thank"]):
        return True

    return False


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────

def check_availability(bm: BrowserManager, config: BotConfig) -> tuple[BookingResult, Optional[str]]:
    """
    Navigate to the restaurant page and check for available slots on the target date.

    Returns (result_status, matched_time_string_or_None).
    Does NOT book – only checks.
    """
    page = bm.page
    target = config.target_date

    logger.info("Checking availability for %s at %s…", config.date, config.restaurant_id)

    page.goto(config.restaurant_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    _human_delay(0.5, 1.0)

    # Set party size first (if applicable)
    _select_party_size(page, config.party_size)

    # Navigate calendar to the right month
    if not _navigate_to_month(page, target.year, target.month):
        logger.warning("Could not navigate to target month")
        bm.screenshot("cal_nav_failed")
        return BookingResult.DATE_UNAVAILABLE, None

    # Click the target date
    if not _click_date(page, target.day):
        logger.info("Date %s does not appear to be available", config.date)
        return BookingResult.DATE_UNAVAILABLE, None

    _human_delay(0.5, 1.0)
    page.wait_for_load_state("networkidle")

    # Find available time slots
    slots = _find_time_slots(page)
    if not slots:
        logger.info("No time slots available for %s", config.date)
        return BookingResult.NO_SLOTS, None

    logger.info("Found %d available slot(s): %s",
                len(slots), ", ".join(t for t, _ in slots))

    best = _pick_best_slot(slots, config.time)
    if best:
        return BookingResult.SUCCESS, best[0]

    return BookingResult.NO_SLOTS, None


def attempt_booking(bm: BrowserManager, config: BotConfig) -> tuple[BookingResult, Optional[str]]:
    """
    Full booking attempt: navigate, find slot, and complete reservation.

    Returns (result_status, booked_time_string_or_None).
    """
    page = bm.page
    target = config.target_date

    logger.info("Attempting booking for %s at %s (party of %d)…",
                config.date, config.restaurant_id, config.party_size)

    page.goto(config.restaurant_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    _human_delay(0.3, 0.7)

    # Set party size
    _select_party_size(page, config.party_size)

    # Navigate to the right month
    if not _navigate_to_month(page, target.year, target.month):
        bm.screenshot("booking_cal_nav_failed")
        return BookingResult.DATE_UNAVAILABLE, None

    # Click date
    if not _click_date(page, target.day):
        return BookingResult.DATE_UNAVAILABLE, None

    _human_delay(0.3, 0.6)
    page.wait_for_load_state("networkidle")

    # Find and pick slot
    slots = _find_time_slots(page)
    if not slots:
        logger.info("No slots available for %s", config.date)
        return BookingResult.NO_SLOTS, None

    logger.info("Available slots: %s", ", ".join(t for t, _ in slots))

    best = _pick_best_slot(slots, config.time)
    if not best:
        return BookingResult.NO_SLOTS, None

    time_str, slot_el = best
    logger.info("Selecting slot: %s", time_str)

    # Click the slot
    slot_el.click()
    _human_delay(0.3, 0.6)

    # Complete booking
    if _confirm_booking(page, bm):
        logger.info("✓ Booking confirmed for %s at %s!", config.date, time_str)
        return BookingResult.SUCCESS, time_str

    bm.screenshot("booking_confirm_failed")
    return BookingResult.BOOKING_FAILED, time_str


def quick_refresh_and_book(bm: BrowserManager, config: BotConfig) -> tuple[BookingResult, Optional[str]]:
    """
    Fast-path booking: reload the current page and attempt to book.

    Used in sniper mode for rapid retries without full navigation.
    """
    page = bm.page

    page.reload(wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    _human_delay(0.1, 0.3)

    target = config.target_date

    # Try clicking the date directly (assume we're on the right month)
    if not _click_date(page, target.day):
        return BookingResult.DATE_UNAVAILABLE, None

    _human_delay(0.1, 0.3)
    page.wait_for_load_state("networkidle")

    slots = _find_time_slots(page)
    if not slots:
        return BookingResult.NO_SLOTS, None

    best = _pick_best_slot(slots, config.time)
    if not best:
        return BookingResult.NO_SLOTS, None

    time_str, slot_el = best
    logger.info("⚡ Sniper: clicking slot %s", time_str)
    slot_el.click()
    _human_delay(0.1, 0.3)

    if _confirm_booking(page, bm):
        return BookingResult.SUCCESS, time_str

    return BookingResult.BOOKING_FAILED, time_str
