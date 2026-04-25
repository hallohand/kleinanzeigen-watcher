from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kleinanzeigen_watcher.parser import Listing, parse_date, parse_listings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def srp_simple_html() -> str:
    return (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")


@pytest.fixture
def srp_plz_html() -> str:
    return (FIXTURES / "srp_plz.html").read_text(encoding="utf-8")


def test_parse_returns_listing_objects(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    assert len(listings) > 20
    assert all(isinstance(l, Listing) for l in listings)


def test_topads_excluded_by_default(srp_simple_html: str) -> None:
    default = parse_listings(srp_simple_html)
    with_topads = parse_listings(srp_simple_html, include_topads=True)
    assert len(with_topads) > len(default)
    assert any(l.is_topad for l in with_topads)
    assert not any(l.is_topad for l in default)


def test_first_listing_has_expected_fields(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    target = next(l for l in listings if l.id == "3391867598")
    assert target.title == "HP Office Monitor 2 Ms 75Hz"
    assert target.price == "55 € VB"
    assert target.location == "26180 Rastede"
    assert target.url.startswith("https://www.kleinanzeigen.de/s-anzeige/")
    assert target.image_url and target.image_url.startswith("https://img.kleinanzeigen.de/")


def test_listing_with_no_price_label(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    target = next(l for l in listings if l.id == "3391823696")
    assert target.price == "VB"


def test_url_is_absolute(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    assert all(l.url.startswith("https://www.kleinanzeigen.de") for l in listings)


def test_unique_ids(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    ids = [l.id for l in listings]
    assert len(ids) == len(set(ids))


def test_listing_id_is_string(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    assert all(isinstance(l.id, str) and l.id.isdigit() for l in listings)


def test_pro_listings_detected(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    assert any(l.is_pro for l in listings)


def test_pro_listings_excludable(srp_simple_html: str) -> None:
    private_only = parse_listings(srp_simple_html, include_pro=False)
    assert all(not l.is_pro for l in private_only)


def test_parse_date_heute() -> None:
    now = datetime(2026, 4, 25, 21, 0)
    result = parse_date("Heute, 19:31", now=now)
    assert result == datetime(2026, 4, 25, 19, 31)


def test_parse_date_gestern() -> None:
    now = datetime(2026, 4, 25, 9, 0)
    result = parse_date("Gestern, 09:14", now=now)
    assert result == datetime(2026, 4, 24, 9, 14)


def test_parse_date_full_date() -> None:
    result = parse_date("23.04.2026")
    assert result == datetime(2026, 4, 23, 0, 0)


def test_parse_date_empty_returns_none() -> None:
    assert parse_date("") is None
    assert parse_date("   ") is None


def test_parse_date_garbage_returns_none() -> None:
    assert parse_date("foo bar") is None


def test_listings_have_parsed_dates(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    has_date = [l for l in listings if l.posted_at is not None]
    assert len(has_date) > 5


def test_plz_fixture_returns_listings(srp_plz_html: str) -> None:
    listings = parse_listings(srp_plz_html)
    assert len(listings) > 0


def test_location_clean_when_no_distance(srp_simple_html: str) -> None:
    listings = parse_listings(srp_simple_html)
    target = next(l for l in listings if l.id == "3391823696")
    assert target.location == "14542 Werder (Havel)"
    assert target.distance is None


def test_distance_extracted_when_radius_search() -> None:
    html = (FIXTURES / "srp_radius_live.html").read_text(encoding="utf-8")
    listings = parse_listings(html)
    target = next(l for l in listings if l.id == "3385062863")
    assert target.location == "28865 Lilienthal"
    assert target.distance == "11 km"


def test_no_internal_whitespace_in_location() -> None:
    html = (FIXTURES / "srp_radius_live.html").read_text(encoding="utf-8")
    listings = parse_listings(html)
    for listing in listings:
        assert "\n" not in listing.location
        assert "  " not in listing.location  # no double-space
