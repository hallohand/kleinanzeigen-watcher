from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .parser import Listing

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_listings (
    id TEXT NOT NULL,
    profile TEXT NOT NULL,
    first_seen_at TIMESTAMP NOT NULL,
    title TEXT,
    price TEXT,
    url TEXT,
    recommended INTEGER,
    verdict_reason TEXT,
    PRIMARY KEY (id, profile)
);
CREATE INDEX IF NOT EXISTS idx_seen_listings_profile ON seen_listings(profile);
"""


class Storage:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cur = self._conn.execute("PRAGMA table_info(seen_listings)")
        cols = {row[1] for row in cur.fetchall()}
        if "recommended" not in cols:
            self._conn.execute("ALTER TABLE seen_listings ADD COLUMN recommended INTEGER")
        if "verdict_reason" not in cols:
            self._conn.execute("ALTER TABLE seen_listings ADD COLUMN verdict_reason TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_listings_recommended "
            "ON seen_listings(profile, recommended, first_seen_at)"
        )

    def has_any_for_profile(self, profile: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen_listings WHERE profile = ? LIMIT 1", (profile,)
        )
        return cur.fetchone() is not None

    def filter_new(self, profile: str, listings: Iterable[Listing]) -> list[Listing]:
        listings = list(listings)
        if not listings:
            return []
        ids = [lst.id for lst in listings]
        placeholders = ",".join("?" * len(ids))
        cur = self._conn.execute(
            f"SELECT id FROM seen_listings WHERE profile = ? AND id IN ({placeholders})",
            (profile, *ids),
        )
        seen = {row[0] for row in cur.fetchall()}
        return [lst for lst in listings if lst.id not in seen]

    def mark_seen(
        self,
        profile: str,
        listings: Iterable[Listing],
        *,
        verdicts: Mapping[str, tuple[bool, str]] | None = None,
    ) -> None:
        listings = list(listings)
        if not listings:
            return
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for lst in listings:
            verdict = (verdicts or {}).get(lst.id)
            rec = 1 if verdict and verdict[0] else (0 if verdict else None)
            reason = verdict[1] if verdict else None
            rows.append((lst.id, profile, now, lst.title, lst.price, lst.url, rec, reason))
        self._conn.executemany(
            "INSERT INTO seen_listings (id, profile, first_seen_at, title, price, url, recommended, verdict_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id, profile) DO UPDATE SET "
            "  recommended = COALESCE(excluded.recommended, seen_listings.recommended), "
            "  verdict_reason = COALESCE(excluded.verdict_reason, seen_listings.verdict_reason), "
            "  title = excluded.title, price = excluded.price, url = excluded.url",
            rows,
        )
        self._conn.commit()

    def get_top_recommended(self, profile: str, *, limit: int = 5) -> list[tuple[Listing, str]]:
        cur = self._conn.execute(
            "SELECT id, title, price, url, verdict_reason "
            "FROM seen_listings "
            "WHERE profile = ? AND recommended = 1 "
            "ORDER BY first_seen_at DESC "
            "LIMIT ?",
            (profile, limit),
        )
        out: list[tuple[Listing, str]] = []
        for row in cur.fetchall():
            id_, title, price, url, reason = row
            listing = Listing(
                id=id_, title=title or "", url=url or "", price=price or "",
                location="", description="", image_url=None, posted_at=None,
                is_topad=False, is_pro=False, distance=None,
            )
            out.append((listing, reason or ""))
        return out

    def close(self) -> None:
        self._conn.close()
