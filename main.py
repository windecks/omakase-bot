#!/usr/bin/env python3
"""
Omakase.in Reservation Bot – Entry Point

Sniper & monitor modes for booking restaurant reservations on omakase.in.
"""

from __future__ import annotations

import sys

from src.browser import BrowserManager
from src.config import load_config
from src.monitor import run_monitor
from src.notifications import print_banner, print_config_summary, setup_logging
from src.sniper import run_sniper


def main(argv: list[str] | None = None) -> int:
    """Run the bot and return an exit code (0 = success)."""
    setup_logging()
    print_banner()

    config = load_config(argv)

    print_config_summary(
        mode=config.mode,
        restaurant_id=config.restaurant_id,
        date=config.date,
        time=config.time,
        party_size=config.party_size,
        auto_book=config.auto_book,
        dry_run=config.dry_run,
    )

    success = False

    try:
        with BrowserManager(config) as bm:
            if config.mode == "sniper":
                success = run_sniper(bm, config)
            elif config.mode == "monitor":
                success = run_monitor(bm, config)
            else:
                print(f"Unknown mode: {config.mode}", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        print("\n\n⏹  Interrupted by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
