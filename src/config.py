"""Configuration loading and validation."""
from __future__ import annotations
import argparse, logging, sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    email: str = ""
    password: str = ""
    restaurant_id: str = ""
    date: str = ""
    time: str = "18:00"
    party_size: int = 2
    mode: str = "sniper"
    auto_book: bool = True
    dry_run: bool = False
    release_time: str = "00:00"
    max_attempts: int = 100
    check_interval: int = 300
    headless: bool = True
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def session_path(self) -> Path: return self.project_root / "session.json"
    @property
    def restaurant_url(self) -> str: return f"https://omakase.in/en/r/{self.restaurant_id}"
    @property
    def reservation_url(self) -> str: return f"https://omakase.in/en/r/{self.restaurant_id}/reservations/new"
    @property
    def target_date(self) -> datetime: return datetime.strptime(self.date, "%Y-%m-%d")

    def validate(self):
        if not all([self.email, self.password, self.restaurant_id, self.date]):
            sys.exit("Missing required config fields: email, password, restaurant_id, date")
        try: datetime.strptime(self.date, "%Y-%m-%d")
        except: sys.exit(f"Invalid date: {self.date} (must be YYYY-MM-DD)")

def load_config(argv: Optional[list[str]] = None) -> BotConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str)
    for k, v in BotConfig.__dataclass_fields__.items():
        if k != "project_root":
            parser.add_argument(f"--{k.replace('_', '-')}", dest=k, type=type(v.default) if type(v.default) != bool else str)
    args, _ = parser.parse_known_args(argv)

    cfg = BotConfig()
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            for k, v in (yaml.safe_load(f) or {}).items(): setattr(cfg, k, v)

    for k, v in vars(args).items():
        if v is not None and k != "config" and hasattr(cfg, k):
            if isinstance(getattr(cfg, k), bool) and isinstance(v, str):
                setattr(cfg, k, v.lower() in ("true", "1", "yes", "on"))
            else: setattr(cfg, k, v)
    cfg.validate()
    return cfg
