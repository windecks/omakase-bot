"""Configuration loading and validation."""
from __future__ import annotations
import argparse, logging, sys, time
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
    party_size: int = 1
    mode: str = "sniper"
    auto_book: bool = False
    discord_webhook_url: str = ""
    discord_user_id: str = ""
    release_time: str = "00:00"
    max_attempts: int = 100
    check_interval: int = 300
    headless: bool = True
    proxy: str = ""
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def session_path(self) -> Path:
        safe_email = "".join(c for c in self.email if c.isalnum() or c in "._-@") or "default"
        sessions_dir = self.project_root / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        return sessions_dir / f"session_{safe_email}.json"
        
    @property
    def account_lock_path(self) -> Path:
        safe_email = "".join(c for c in self.email if c.isalnum() or c in "._-@") or "default"
        sessions_dir = self.project_root / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        return sessions_dir / f"hold_lock_{safe_email}.txt"

    def set_account_lock(self, minutes: int = 5):
        expiry = time.time() + (minutes * 60)
        self.account_lock_path.write_text(str(expiry))

    def get_account_lock_remaining(self) -> float:
        try:
            if self.account_lock_path.exists():
                expiry = float(self.account_lock_path.read_text().strip())
                return max(0.0, expiry - time.time())
        except:
            pass
        return 0.0

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
