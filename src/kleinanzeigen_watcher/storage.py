from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .parser import Listing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_listings (
    id TEXT NOT NULL,
    profile TEXT NOT NULL,
    first_seen_at TIMESTAMP NOT NULL,
    title TEXT,
    price TEXT,
    url TEXT,
    PRIMARY KEY (id, profile)
);
CREATE INDEX IF NOT EXISTS idx_seen_listings_profile ON seen_listings(profile);
"""


class Storage:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def has_any_for_profile(self, profile: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen_listings WHERE profile = ? LIMIT 1", (profile,)
        )
        return cur.fetchone() is not None

    def filter_new(self, profile: str, listings: Iterable[Listing]) -> list[Listing]:
        listings = list(listings)
        if not listings:
            return []
        ids = [l.id for l in listings]
        placeholders = ",".join("?" * len(ids))
        cur = self._conn.execute(
            f"SELECT id FROM seen_listings WHERE profile = ? AND id IN ({placeholders})",
            (profile, *ids),
        )
        seen = {row[0] for row in cur.fetchall()}
        return [l for l in listings if l.id not in seen]

    def mark_seen(self, profile: str, listings: Iterable[Listing]) -> None:
        rows = [
            (l.id, profile, datetime.now().isoformat(timespec="seconds"), l.title, l.price, l.url)
            for l in listings
        ]
        if not rows:
            return
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen_listings (id, profile, first_seen_at, title, price, url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
