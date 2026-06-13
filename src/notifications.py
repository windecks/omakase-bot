"""
Notification system.

Provides colored terminal output and macOS system sound alerts.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
# ANSI color codes
# ────────────────────────────────────────────────────────────────────────

class _Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"


def _supports_color() -> bool:
    """Check if the terminal supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _c(color: str, text: str) -> str:
    """Wrap text in color codes if supported."""
    if not _COLOR:
        return text
    return f"{color}{text}{_Colors.RESET}"


# ────────────────────────────────────────────────────────────────────────
# Custom log formatter
# ────────────────────────────────────────────────────────────────────────

class ColorFormatter(logging.Formatter):
    """Logging formatter with ANSI colors for different log levels."""

    _LEVEL_COLORS = {
        logging.DEBUG: _Colors.DIM,
        logging.INFO: _Colors.CYAN,
        logging.WARNING: _Colors.YELLOW,
        logging.ERROR: _Colors.RED,
        logging.CRITICAL: _Colors.RED + _Colors.BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        if _COLOR:
            color = self._LEVEL_COLORS.get(record.levelno, "")
            record.levelname = f"{color}{record.levelname:<8}{_Colors.RESET}"
            record.msg = f"{color}{record.msg}{_Colors.RESET}"
        return super().format(record)


def setup_logging(verbose: bool = False) -> None:
    """Configure root logger with colored output."""
    level = logging.DEBUG if verbose else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        ColorFormatter("%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s",
                       datefmt="%H:%M:%S")
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Remove any existing handlers
    root.handlers.clear()
    root.addHandler(handler)


# ────────────────────────────────────────────────────────────────────────
# Alert methods
# ────────────────────────────────────────────────────────────────────────

def play_sound() -> None:
    """Play a system alert sound on macOS."""
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Glass.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # Not on macOS or afplay not available
        print("\a", end="", flush=True)


def notify_slot_found(date: str, time: str, restaurant_id: str, url: str | None = None) -> None:
    """Announce that an available slot was found."""
    msg = (
        f"\n{'═' * 60}\n"
        f"  🍣  SLOT FOUND!\n"
        f"  Restaurant: {restaurant_id}\n"
        f"  Date: {date}  |  Time: {time}\n"
    )
    if url:
        msg += f"  Link: {url}\n"
    msg += f"{'═' * 60}\n"
    print(_c(_Colors.GREEN + _Colors.BOLD, msg))
    play_sound()


def notify_booking_success(date: str, time: str, restaurant_id: str, url: str | None = None) -> None:
    """Announce successful booking."""
    msg = (
        f"\n{'═' * 60}\n"
        f"  ✅  BOOKING CONFIRMED!\n"
        f"  Restaurant: {restaurant_id}\n"
        f"  Date: {date}  |  Time: {time}\n"
    )
    if url:
        msg += f"  Link: {url}\n"
    msg += f"{'═' * 60}\n"
    print(_c(_Colors.GREEN + _Colors.BOLD, msg))
    # Play sound 3 times for emphasis
    for _ in range(3):
        play_sound()


def notify_booking_failed(reason: str) -> None:
    """Announce booking failure."""
    msg = (
        f"\n{'═' * 60}\n"
        f"  ❌  BOOKING FAILED\n"
        f"  Reason: {reason}\n"
        f"{'═' * 60}\n"
    )
    print(_c(_Colors.RED + _Colors.BOLD, msg))
    play_sound()


def notify_waiting(message: str) -> None:
    """Print a waiting/status message."""
    print(_c(_Colors.DIM, f"  ⏳ {message}"))


def print_banner() -> None:
    """Print the startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🍣  Omakase.in Reservation Bot                      ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""
    print(_c(_Colors.CYAN + _Colors.BOLD, banner))


def print_config_summary(
    mode: str,
    restaurant_id: str,
    date: str,
    time: str,
    party_size: int,
    auto_book: bool,
) -> None:
    """Print a summary of the bot configuration."""
    lines = [
        f"  Mode:        {_c(_Colors.MAGENTA, mode.upper())}",
        f"  Restaurant:  {_c(_Colors.CYAN, restaurant_id)}",
        f"  Date:        {_c(_Colors.CYAN, date)}",
        f"  Time:        {_c(_Colors.CYAN, time)}",
        f"  Party:       {_c(_Colors.CYAN, str(party_size))}",
        f"  Auto-book:   {_c(_Colors.GREEN if auto_book else _Colors.YELLOW, str(auto_book))}",
    ]
    lines.append("")
    print("\n".join(lines))
