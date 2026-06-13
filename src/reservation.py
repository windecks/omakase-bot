"""Core reservation logic."""
from __future__ import annotations
import logging, random, time, re
from enum import Enum
from typing import Optional
from playwright.sync_api import Page
from src.browser import BrowserManager
from src.config import BotConfig

logger = logging.getLogger(__name__)

class BookingResult(Enum):
    SUCCESS = "success"
    NO_SLOTS = "no_slots"
    DATE_UNAVAILABLE = "date_unavailable"
    BOOKING_FAILED = "booking_failed"
    ALREADY_BOOKED = "already_booked"

def _delay(low=0.2, high=0.5): time.sleep(random.uniform(low, high))

def _nav_month(page: Page, t_yr: int, t_mo: int) -> bool:
    for _ in range(12):
        loc = page.locator(".calendar-header, .datepicker-switch, th.month, [class*='month'], [class*='header']:has-text('20')").first
        if not loc.is_visible(timeout=3000): return False
        txt = loc.text_content() or ""
        c_yr, c_mo = t_yr, t_mo
        if m := re.search(r"(\d{4})\D+(\d{1,2})", txt): c_yr, c_mo = int(m.group(1)), int(m.group(2))
        elif m := re.search(r"(\d{1,2})/(\d{4})", txt): c_mo, c_yr = int(m.group(1)), int(m.group(2))
        else:
            for i, mo in enumerate(["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1):
                if mo in txt.lower() and (y := re.search(r"20\d{2}", txt)): c_yr, c_mo = int(y.group()), i
        if c_yr == t_yr and c_mo == t_mo: return True
        btn_sel = ".calendar-next, .next, a:has(i[class*='right'])" if (t_yr*12+t_mo) > (c_yr*12+c_mo) else ".calendar-prev, .prev, a:has(i[class*='left'])"
        page.locator(btn_sel).first.click()
        _delay()
    return False

def _click_date(page: Page, day: int) -> bool:
    loc = page.locator(f"td:not(.disabled):not(.past):not(.unavailable) a:text-is('{day}'), a:not(.disabled):not(.unavailable):text-is('{day}'), .day:not(.disabled):text-is('{day}')").first
    if loc.is_visible(timeout=2000):
        loc.click()
        return True
    page.screenshot(path=f"debug_click_date_failed_{day}.png")
    return False

def _find_slots(page: Page) -> list[tuple[str, any]]:
    slots = []
    selectors = (
        "input[name='inventoryGroup'] + label, "
        ".p-rsv_c_select_item li label, "
        "a[class*='slot'], button[class*='slot'], div[class*='slot'], "
        "a[class*='time'], button[class*='time'], "
        ".available-slot, .time-slot, [data-time]"
    )
    for el in page.locator(selectors).all():
        c = (el.get_attribute("class") or "").lower()
        if "disabled" in c or "unavailable" in c or "sold" in c: continue
        if m := re.search(r"(\d{1,2}:\d{2})", el.text_content() or ""): slots.append((m.group(1), el))
        elif dt := el.get_attribute("data-time"): slots.append((dt, el))
    return list({s[0]: s for s in slots}.values())

def _pick_best(slots: list[tuple[str, any]], pref: str) -> Optional[tuple[str, any]]:
    if not slots: return None
    return min(slots, key=lambda s: abs((int(s[0].split(":")[0])*60 + int(s[0].split(":")[1])) - (int(pref.split(":")[0])*60 + int(pref.split(":")[1]))))

def _confirm(page: Page, cfg: BotConfig) -> bool:
    _delay()
    try: page.locator("label:has-text('Number of guests') + .ui.dropdown").click(timeout=1000)
    except: pass
    try: page.locator(f".ui.dropdown .menu .item:text-is('{cfg.party_size}')").click(timeout=1000)
    except: pass

    for _ in range(3):
        if page.locator("text='Reservation confirmed', [class*='success']").first.is_visible(timeout=1000): return True
        btn = page.locator("button:has-text('Proceed to review'), button:has-text('Confirm'), button:has-text('Complete')").first
        if btn.is_visible(timeout=3000):
            if not cfg.auto_book and "review" not in (btn.text_content() or "").lower(): return True
            try: btn.click(force=True)
            except: pass
            _delay(1, 2)
    return page.locator("text='Reservation confirmed', [class*='success']").first.is_visible(timeout=2000)

def attempt_booking(bm: BrowserManager, cfg: BotConfig) -> tuple[BookingResult, Optional[str], Optional[str]]:
    bm.page.goto(cfg.restaurant_url, wait_until="domcontentloaded")
    bm.page.goto(cfg.reservation_url, wait_until="domcontentloaded")
    try: bm.page.wait_for_load_state("networkidle", timeout=3000)
    except: pass
    if not _nav_month(bm.page, cfg.target_date.year, cfg.target_date.month) or not _click_date(bm.page, cfg.target_date.day):
        return BookingResult.DATE_UNAVAILABLE, None, None
    
    try: bm.page.locator(".p-rsv_c_empty").wait_for(state="hidden", timeout=4000)
    except: pass
    try: bm.page.locator(".ui.active.dimmer, .loading, .loader").wait_for(state="hidden", timeout=4000)
    except: pass
    
    slots = []
    for _ in range(15):
        slots = _find_slots(bm.page)
        if slots: break
        txt = (bm.page.locator(".p-rsv_c_selectWrap").text_content() or "").lower()
        if any(w in txt for w in ["sold out", "no slot", "not available", "no available", "no course", "full"]):
            break
        bm.page.wait_for_timeout(200)
    
    best = _pick_best(slots, cfg.time)
    if not best: return BookingResult.NO_SLOTS, None, None
    best[1].click()
    _delay()
    try: bm.page.locator("input[name='course'] + label").first.click(timeout=1000)
    except: pass

    success = _confirm(bm.page, cfg)
    return (BookingResult.SUCCESS, best[0], bm.page.url) if success else (BookingResult.BOOKING_FAILED, best[0], None)

def quick_refresh_and_book(bm: BrowserManager, cfg: BotConfig) -> tuple[BookingResult, Optional[str], Optional[str]]:
    bm.page.reload(wait_until="domcontentloaded")
    if not _click_date(bm.page, cfg.target_date.day): return BookingResult.DATE_UNAVAILABLE, None, None
    
    try: bm.page.locator(".p-rsv_c_empty").wait_for(state="hidden", timeout=4000)
    except: pass
    try: bm.page.locator(".ui.active.dimmer, .loading, .loader").wait_for(state="hidden", timeout=4000)
    except: pass
    
    slots = []
    for _ in range(15):
        slots = _find_slots(bm.page)
        if slots: break
        txt = (bm.page.locator(".p-rsv_c_selectWrap").text_content() or "").lower()
        if any(w in txt for w in ["sold out", "no slot", "not available", "no available", "no course", "full"]):
            break
        bm.page.wait_for_timeout(200)
    
    best = _pick_best(slots, cfg.time)
    if not best: return BookingResult.NO_SLOTS, None, None
    best[1].click()
    _delay()
    success = _confirm(bm.page, cfg)
    return (BookingResult.SUCCESS, best[0], bm.page.url) if success else (BookingResult.BOOKING_FAILED, best[0], None)
