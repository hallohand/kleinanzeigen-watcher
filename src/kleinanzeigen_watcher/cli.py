from __future__ import annotations

import argparse
import logging
import sys
from typing import IO

from .fetcher import FetchError, Fetcher
from .parser import parse_listings
from .url_builder import build_search_url

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kleinanzeigen-watcher",
        description="Polls kleinanzeigen.de search results and notifies via Telegram on new listings.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test", help="Fetch a single search and print parsed listings (no telegram, no db).")
    test.add_argument("--query", required=False, help="Search term (free text).")
    test.add_argument("--plz", required=False, help="Postal code.")
    test.add_argument("--radius", type=int, default=None, help="Search radius in km (requires --plz).")
    test.add_argument("--price-min", type=int, default=None, dest="price_min")
    test.add_argument("--price-max", type=int, default=None, dest="price_max")
    test.add_argument("--shipping", choices=["ja", "nein", "any"], default="any")
    test.add_argument("--category", type=int, default=None, dest="category_id")
    test.add_argument("--max-results", type=int, default=10, dest="max_results")
    test.add_argument("--include-topads", action="store_true", dest="include_topads")

    run = sub.add_parser("run", help="Start the main polling loop using config.yaml.")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--bootstrap", action="store_true", help="Mark current listings as seen and exit (no notifications).")
    run.add_argument("-v", "--verbose", action="store_true")

    return parser


def cmd_test(args: argparse.Namespace, *, fetcher: Fetcher, stdout: IO[str] | None = None) -> int:
    out = stdout or sys.stdout
    if not args.query and not args.category_id:
        print("error: --query or --category required", file=out)
        return 2

    url = build_search_url(
        query=args.query,
        plz=args.plz,
        radius_km=args.radius,
        price_min=args.price_min,
        price_max=args.price_max,
        shipping=args.shipping,
        category_id=args.category_id,
    )
    print(f"GET {url}", file=out)

    try:
        html = fetcher.fetch(url)
    except FetchError as exc:
        print(f"fetch failed: {exc}", file=out)
        return 1

    listings = parse_listings(html, include_topads=args.include_topads)
    print(f"parsed {len(listings)} listings (showing up to {args.max_results}):\n", file=out)
    for listing in listings[: args.max_results]:
        print(f"- {listing.title}", file=out)
        print(f"  {listing.price} | {listing.location} | {listing.posted_at}", file=out)
        print(f"  {listing.url}", file=out)
        print(file=out)

    return 0
