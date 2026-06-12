"""
Configuration loading and validation.

Merges YAML config files with CLI argument overrides into a single,
validated BotConfig dataclass.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# Data model
# ────────────────────────────────────────────────────────────────────────

@dataclass
class BotConfig:
    """Complete, validated bot configuration."""

    # Account
    email: str = ""
    password: str = ""

    # Target
    restaurant_id: str = ""
    date: str = ""            # YYYY-MM-DD
    time: str = "18:00"       # HH:MM preferred time
    party_size: int = 2

    # Mode
    mode: str = "sniper"      # "sniper" | "monitor"
    auto_book: bool = True

    # Sniper
    release_time: str = "00:00"   # HH:MM in JST
    max_attempts: int = 100

    # Monitor
    check_interval: int = 300     # seconds

    # Browser
    headless: bool = True

    # Internal (derived at runtime)
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    # ── Helpers ──────────────────────────────────────────────────────

    @property
    def session_path(self) -> Path:
        return self.project_root / "session.json"

    @property
    def restaurant_url(self) -> str:
        return f"https://omakase.in/en/r/{self.restaurant_id}"

    @property
    def target_date(self) -> datetime:
        return datetime.strptime(self.date, "%Y-%m-%d")

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: list[str] = []

        if not self.email:
            errors.append("'email' is required")
        if not self.password:
            errors.append("'password' is required")
        if not self.restaurant_id:
            errors.append("'restaurant_id' is required")
        if not self.date:
            errors.append("'date' is required")

        # Date format
        if self.date:
            try:
                datetime.strptime(self.date, "%Y-%m-%d")
            except ValueError:
                errors.append(f"'date' must be YYYY-MM-DD, got '{self.date}'")

        # Time format
        for label, value in [("time", self.time), ("release_time", self.release_time)]:
            try:
                parts = value.split(":")
                if len(parts) != 2:
                    raise ValueError
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                errors.append(f"'{label}' must be HH:MM, got '{value}'")

        if self.mode not in ("sniper", "monitor"):
            errors.append(f"'mode' must be 'sniper' or 'monitor', got '{self.mode}'")
        if self.party_size < 1:
            errors.append(f"'party_size' must be >= 1, got {self.party_size}")
        if self.check_interval < 10:
            errors.append(f"'check_interval' must be >= 10, got {self.check_interval}")
        if self.max_attempts < 1:
            errors.append(f"'max_attempts' must be >= 1, got {self.max_attempts}")

        return errors


# ────────────────────────────────────────────────────────────────────────
# Loading
# ────────────────────────────────────────────────────────────────────────

def _load_yaml(path: str) -> dict:
    """Load a YAML config file and return its contents as a dict."""
    config_path = Path(path)
    if not config_path.exists():
        logger.error("Config file not found: %s", path)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        logger.error("Config file must contain a YAML mapping, got %s", type(data).__name__)
        sys.exit(1)

    return data


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Omakase.in reservation bot – sniper & monitor modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--config", "-c", type=str, default=None,
                        help="Path to YAML config file")

    # Allow every config field to be overridden via CLI
    parser.add_argument("--email", type=str, default=None)
    parser.add_argument("--password", type=str, default=None)
    parser.add_argument("--restaurant-id", type=str, default=None, dest="restaurant_id")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--time", type=str, default=None)
    parser.add_argument("--party-size", type=int, default=None, dest="party_size")
    parser.add_argument("--mode", type=str, choices=["sniper", "monitor"], default=None)
    parser.add_argument("--auto-book", type=_str_to_bool, default=None, dest="auto_book",
                        help="true/false – auto-complete booking")
    parser.add_argument("--release-time", type=str, default=None, dest="release_time",
                        help="HH:MM in JST when slots drop (sniper mode)")
    parser.add_argument("--max-attempts", type=int, default=None, dest="max_attempts")
    parser.add_argument("--check-interval", type=int, default=None, dest="check_interval")
    parser.add_argument("--headless", type=_str_to_bool, default=None,
                        help="true/false – run browser headless")

    return parser


def _str_to_bool(value: str) -> bool:
    """Parse boolean-like strings for argparse."""
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got '{value}'")


def load_config(argv: Optional[list[str]] = None) -> BotConfig:
    """
    Load configuration by merging (in priority order):
        1. CLI arguments  (highest)
        2. YAML config file
        3. BotConfig defaults  (lowest)
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Start from defaults
    cfg = BotConfig()

    # Layer on YAML values
    if args.config:
        yaml_data = _load_yaml(args.config)
        for key, value in yaml_data.items():
            if hasattr(cfg, key) and value is not None:
                setattr(cfg, key, value)

    # Layer on CLI overrides
    cli_overrides = {k: v for k, v in vars(args).items() if v is not None and k != "config"}
    for key, value in cli_overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)

    # Validate
    errors = cfg.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        sys.exit(1)

    return cfg
