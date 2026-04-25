from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from selectolax.parser import HTMLParser, Node

from .url_builder import BASE_URL


@dataclass(frozen=True)
class Listing:
    id: str
    title: str
    url: str
    price: str
    location: str
    description: str
    image_url: str | None
    posted_at: datetime | None
    is_topad: bool
    is_pro: bool
    distance: str | None = None


_HEUTE_RE = re.compile(r"^Heute,\s*(\d{1,2}):(\d{2})$")
_GESTERN_RE = re.compile(r"^Gestern,\s*(\d{1,2}):(\d{2})$")
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_DISTANCE_RE = re.compile(r"\((\d+)\s*km\)")


def parse_date(text: str, *, now: datetime | None = None) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    now = now or datetime.now()
    if m := _HEUTE_RE.match(text):
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if m := _GESTERN_RE.match(text):
        y = (now - timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return y
    if m := _DATE_RE.match(text):
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _text(node: Node | None) -> str:
    return node.text(strip=True) if node else ""


def _parse_location_and_distance(node: Node | None) -> tuple[str, str | None]:
    if node is None:
        return "", None
    raw = node.text(strip=True)
    distance = None
    if m := _DISTANCE_RE.search(raw):
        distance = f"{m.group(1)} km"
    location = _DISTANCE_RE.sub("", raw)
    location = " ".join(location.split())  # collapse all whitespace runs
    return location, distance


def _is_topad(article: Node) -> bool:
    parent = article.parent
    if not parent:
        return False
    cls = parent.attributes.get("class") or ""
    return "is-topad" in cls or "badge-topad" in cls


def _parse_one(article: Node, now: datetime | None) -> Listing | None:
    adid = article.attributes.get("data-adid")
    href = article.attributes.get("data-href")
    if not adid or not href:
        return None

    title = _text(article.css_first("h2.text-module-begin"))
    price = _text(article.css_first("p.aditem-main--middle--price-shipping--price"))
    location, distance = _parse_location_and_distance(article.css_first("div.aditem-main--top--left"))
    description = _text(article.css_first("p.aditem-main--middle--description"))
    date_raw = _text(article.css_first("div.aditem-main--top--right"))

    img = article.css_first("div.aditem-image img")
    image_url = img.attributes.get("src") if img else None

    is_pro = article.css_first("div.badge-hint-pro-small-srp") is not None

    return Listing(
        id=adid,
        title=title,
        url=BASE_URL + href if href.startswith("/") else href,
        price=price,
        location=location,
        description=description,
        image_url=image_url,
        posted_at=parse_date(date_raw, now=now),
        is_topad=_is_topad(article),
        is_pro=is_pro,
        distance=distance,
    )


def parse_listings(
    html: str,
    *,
    include_topads: bool = False,
    include_pro: bool = True,
    now: datetime | None = None,
) -> list[Listing]:
    tree = HTMLParser(html)
    out: list[Listing] = []
    for article in tree.css("article.aditem"):
        listing = _parse_one(article, now)
        if listing is None:
            continue
        if listing.is_topad and not include_topads:
            continue
        if listing.is_pro and not include_pro:
            continue
        out.append(listing)
    return out
