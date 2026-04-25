from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import IO

import httpx
from dotenv import load_dotenv

from .config import load_config
from .evaluator import DEFAULT_SYSTEM_PROMPT, Evaluator
from .fetcher import FetchError, Fetcher
from .logging_setup import setup_logging
from .notifier import Notifier
from .parser import parse_listings
from .scheduler import Scheduler
from .storage import Storage
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
    run.add_argument("--env-file", default=".env", dest="env_file")
    run.add_argument("--log-dir", default=None, dest="log_dir")
    run.add_argument("--bootstrap", action="store_true", help="Poll each profile once, mark as seen, and exit (no notifications).")
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
        loc = f"{listing.location} ({listing.distance})" if listing.distance else listing.location
        print(f"- {listing.title}", file=out)
        print(f"  {listing.price} | {loc} | {listing.posted_at}", file=out)
        print(f"  {listing.url}", file=out)
        print(file=out)

    return 0


def cmd_run(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    if env is None:
        env_path = Path(args.env_file)
        if env_path.exists():
            load_dotenv(env_path)
        env = dict(os.environ)

    try:
        config = load_config(args.config, env=env)
    except (ValueError, OSError) as exc:
        log.error("config error: %s", exc)
        return 2

    log_dir = Path(args.log_dir) if args.log_dir else None
    setup_logging(verbose=args.verbose, log_dir=log_dir)

    storage = Storage(config.db_path)
    fetcher = Fetcher(
        user_agents=config.user_agents,
        min_delay_seconds=config.request_delay_seconds,
        transport=transport,
    )
    notifier = Notifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        transport=transport,
    )
    evaluator: Evaluator | None = None
    if config.anthropic_api_key and any(p.ai_filter for p in config.profiles):
        custom_prompt = next((p.evaluator_prompt for p in config.profiles if p.ai_filter and p.evaluator_prompt), None)
        evaluator = Evaluator(
            api_key=config.anthropic_api_key,
            system_prompt=custom_prompt or DEFAULT_SYSTEM_PROMPT,
        )
    scheduler = Scheduler(
        profiles=config.profiles,
        fetcher=fetcher,
        storage=storage,
        notifier=notifier,
        evaluator=evaluator,
    )

    try:
        if args.bootstrap:
            scheduler.run_until(deadline_iterations=1)
        else:
            scheduler.install_signal_handlers()
            scheduler.run_forever()
    finally:
        fetcher.close()
        notifier.close()
        storage.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "test":
        fetcher = Fetcher(
            user_agents=[
                "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
            ],
            min_delay_seconds=0.0,
        )
        try:
            return cmd_test(args, fetcher=fetcher)
        finally:
            fetcher.close()
    if args.command == "run":
        return cmd_run(args)
    parser.print_help()
    return 2
