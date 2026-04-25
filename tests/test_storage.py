from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kleinanzeigen_watcher.parser import Listing
from kleinanzeigen_watcher.storage import Storage


def _listing(id_: str, title: str = "T") -> Listing:
    return Listing(
        id=id_,
        title=title,
        url=f"https://www.kleinanzeigen.de/s-anzeige/x/{id_}",
        price="1 €",
        location="X",
        description="",
        image_url=None,
        posted_at=datetime(2026, 4, 25, 12, 0),
        is_topad=False,
        is_pro=False,
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test.db")


def test_fresh_db_has_no_listings(storage: Storage) -> None:
    assert storage.has_any_for_profile("p1") is False


def test_filter_new_returns_all_when_db_empty(storage: Storage) -> None:
    listings = [_listing("1"), _listing("2")]
    assert storage.filter_new("p1", listings) == listings


def test_mark_seen_then_filter_new_returns_empty(storage: Storage) -> None:
    listings = [_listing("1"), _listing("2")]
    storage.mark_seen("p1", listings)
    assert storage.filter_new("p1", listings) == []


def test_filter_new_returns_partial_overlap(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("1")])
    new = _listing("2")
    assert storage.filter_new("p1", [_listing("1"), new]) == [new]


def test_same_id_for_different_profiles_is_not_shared(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("1")])
    assert storage.filter_new("p2", [_listing("1")]) == [_listing("1")]


def test_has_any_for_profile_after_mark(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("1")])
    assert storage.has_any_for_profile("p1") is True
    assert storage.has_any_for_profile("p2") is False


def test_mark_seen_idempotent(storage: Storage) -> None:
    listings = [_listing("1")]
    storage.mark_seen("p1", listings)
    storage.mark_seen("p1", listings)
    assert storage.filter_new("p1", listings) == []


def test_mark_seen_empty_list_is_noop(storage: Storage) -> None:
    storage.mark_seen("p1", [])
    assert storage.has_any_for_profile("p1") is False


def test_storage_persists_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    s1 = Storage(db_path)
    s1.mark_seen("p1", [_listing("1")])
    s1.close()

    s2 = Storage(db_path)
    assert s2.filter_new("p1", [_listing("1")]) == []
    s2.close()


def test_filter_new_preserves_order(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("2")])
    listings = [_listing("1"), _listing("2"), _listing("3")]
    new = storage.filter_new("p1", listings)
    assert [lst.id for lst in new] == ["1", "3"]


def test_mark_seen_with_verdicts_persists_recommended_and_reason(storage: Storage) -> None:
    listings = [_listing("1", "Dell"), _listing("2", "Junk")]
    verdicts = {"1": (True, "Dell, gut"), "2": (False, "no-name")}
    storage.mark_seen("p1", listings, verdicts=verdicts)

    top = storage.get_top_recommended("p1", limit=10)
    assert len(top) == 1
    assert top[0][0].id == "1"
    assert top[0][1] == "Dell, gut"


def test_mark_seen_without_verdicts_leaves_recommended_null(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("1")])
    assert storage.get_top_recommended("p1", limit=10) == []


def test_get_top_recommended_orders_by_first_seen_desc(storage: Storage, tmp_path: Path) -> None:
    import time
    storage.mark_seen("p1", [_listing("1")], verdicts={"1": (True, "first")})
    time.sleep(1.1)  # crude but deterministic — first_seen_at uses second resolution
    storage.mark_seen("p1", [_listing("2")], verdicts={"2": (True, "second")})

    top = storage.get_top_recommended("p1", limit=10)
    assert [lst.id for lst, _ in top] == ["2", "1"]


def test_get_top_recommended_limit_caps_results(storage: Storage) -> None:
    listings = [_listing(str(i)) for i in range(8)]
    verdicts = {str(i): (True, f"r{i}") for i in range(8)}
    storage.mark_seen("p1", listings, verdicts=verdicts)
    assert len(storage.get_top_recommended("p1", limit=5)) == 5


def test_re_evaluation_updates_verdict(storage: Storage) -> None:
    storage.mark_seen("p1", [_listing("1")])  # first seen, no verdict
    assert storage.get_top_recommended("p1", limit=10) == []

    storage.mark_seen("p1", [_listing("1", "Dell update")], verdicts={"1": (True, "actually good")})
    top = storage.get_top_recommended("p1", limit=10)
    assert len(top) == 1
    assert top[0][1] == "actually good"


def test_legacy_db_without_new_columns_is_migrated(tmp_path: Path) -> None:
    import sqlite3
    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(str(db_path))
    con.executescript("""
        CREATE TABLE seen_listings (
            id TEXT NOT NULL, profile TEXT NOT NULL, first_seen_at TIMESTAMP NOT NULL,
            title TEXT, price TEXT, url TEXT, PRIMARY KEY (id, profile)
        );
    """)
    con.execute(
        "INSERT INTO seen_listings VALUES (?, ?, ?, ?, ?, ?)",
        ("oldid", "p1", "2026-01-01T00:00:00", "Old", "1 €", "https://x"),
    )
    con.commit()
    con.close()

    storage = Storage(db_path)
    assert storage.has_any_for_profile("p1") is True
    storage.mark_seen("p1", [_listing("new")], verdicts={"new": (True, "ok")})
    top = storage.get_top_recommended("p1", limit=10)
    assert len(top) == 1
    assert top[0][0].id == "new"
    storage.close()
