from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]
DEFAULT_DB_PATH = Path("kleinanzeigen.db")


@dataclass(frozen=True)
class Profile:
    name: str
    query: str | None = None
    plz: str | None = None
    radius_km: int | None = None
    price_min: int | None = None
    price_max: int | None = None
    shipping: str = "any"
    condition: str | None = None
    category_id: int | None = None
    poll_interval_minutes: int = 10
    enabled: bool = True
    include_topads: bool = False
    include_pro: bool = True


@dataclass(frozen=True)
class Config:
    profiles: list[Profile]
    user_agents: list[str]
    request_delay_seconds: float
    telegram_bot_token: str
    telegram_chat_id: str
    db_path: Path = DEFAULT_DB_PATH

    def active_profiles(self) -> list[Profile]:
        return [p for p in self.profiles if p.enabled]


def _coerce_plz(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _build_profile(raw: dict[str, object], defaults: dict[str, object]) -> Profile:
    if "name" not in raw or not raw["name"]:
        raise ValueError("profile missing 'name'")
    name = str(raw["name"])
    enabled = bool(raw.get("enabled", True))
    query = raw.get("query")
    category_id = raw.get("category_id")
    if not query and category_id is None:
        raise ValueError(f"profile '{name}' needs at least 'query' or 'category_id'")
    plz = _coerce_plz(raw.get("plz"))
    radius_km = raw.get("radius_km")
    if radius_km is not None and plz is None:
        raise ValueError(f"profile '{name}' has radius_km but no plz")
    poll_interval = int(raw.get("poll_interval_minutes", defaults.get("poll_interval_minutes", 10)))
    return Profile(
        name=name,
        enabled=enabled,
        query=str(query) if query else None,
        plz=plz,
        radius_km=int(radius_km) if radius_km is not None else None,
        price_min=int(raw["price_min"]) if raw.get("price_min") is not None else None,
        price_max=int(raw["price_max"]) if raw.get("price_max") is not None else None,
        shipping=str(raw.get("shipping", "any")),
        condition=str(raw["condition"]) if raw.get("condition") else None,
        category_id=int(category_id) if category_id is not None else None,
        poll_interval_minutes=poll_interval,
        include_topads=bool(raw.get("include_topads", False)),
        include_pro=bool(raw.get("include_pro", True)),
    )


def load_config(path: Path | str, *, env: dict[str, str] | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN missing in environment")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID missing in environment")

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults: dict[str, object] = raw.get("defaults") or {}
    raw_profiles: list[dict[str, object]] = raw.get("profiles") or []
    profiles = [_build_profile(p, defaults) for p in raw_profiles]

    user_agents = list(defaults.get("user_agents") or DEFAULT_USER_AGENTS)
    request_delay = float(defaults.get("request_delay_seconds", 5.0))
    db_path = Path(str(defaults.get("db_path", DEFAULT_DB_PATH)))

    return Config(
        profiles=profiles,
        user_agents=user_agents,
        request_delay_seconds=request_delay,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        db_path=db_path,
    )
