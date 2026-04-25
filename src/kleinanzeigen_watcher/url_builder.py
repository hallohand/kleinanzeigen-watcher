from __future__ import annotations

BASE_URL = "https://www.kleinanzeigen.de"

_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "ß": "ss",
})


def _slugify(text: str) -> str:
    return text.translate(_UMLAUT_MAP).lower().strip().replace(" ", "-")


def build_search_url(
    *,
    query: str | None = None,
    plz: str | None = None,
    radius_km: int | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    shipping: str = "any",
    condition: str | None = None,
    category_id: int | None = None,
    page: int = 1,
    sort_by_date: bool = True,
) -> str:
    if query is None and category_id is None:
        raise ValueError("query or category_id required")
    if radius_km is not None and plz is None:
        raise ValueError("radius_km requires plz")

    prefix_tokens: list[str] = []
    if page > 1:
        prefix_tokens.append(f"seite:{page}")
    if plz is not None:
        prefix_tokens.append(plz)
    if price_min is not None or price_max is not None:
        prefix_tokens.append(f"preis:{price_min or ''}:{price_max or ''}")

    slug = _slugify(query) if query else ""

    suffix_parts: list[str] = []
    if slug:
        suffix_parts.append(slug)
    if shipping in ("ja", "nein"):
        suffix_parts.append(f"versand:{shipping}")

    cat_token = f"c{category_id}" if category_id is not None else "k0"
    location_suffix = ""
    if plz is not None:
        location_suffix = "l1" + (f"r{radius_km}" if radius_km is not None else "")
    condition_suffix = f"+global.zustand:{condition}" if condition else ""

    segments = prefix_tokens + suffix_parts + [cat_token + location_suffix + condition_suffix]
    path = "/s-" + segments[0]
    if len(segments) > 1:
        path += "/" + "/".join(segments[1:])

    query_str = "?sortingField=SORTING_DATE" if sort_by_date else ""
    return f"{BASE_URL}{path}{query_str}"
