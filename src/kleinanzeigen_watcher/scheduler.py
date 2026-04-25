from __future__ import annotations

import logging
import signal
import time
from typing import TYPE_CHECKING

from .fetcher import FetchError
from .parser import parse_listings
from .url_builder import build_search_url

if TYPE_CHECKING:
    from .config import Profile
    from .fetcher import Fetcher
    from .notifier import Notifier
    from .storage import Storage

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        profiles: list[Profile],
        fetcher: Fetcher,
        storage: Storage,
        notifier: Notifier,
    ) -> None:
        self._profiles = profiles
        self._fetcher = fetcher
        self._storage = storage
        self._notifier = notifier
        self._stop_requested = False

    def poll_once(self, profile: Profile, *, bootstrap: bool = False) -> int:
        url = build_search_url(
            query=profile.query,
            plz=profile.plz,
            radius_km=profile.radius_km,
            price_min=profile.price_min,
            price_max=profile.price_max,
            shipping=profile.shipping,
            condition=profile.condition,
            category_id=profile.category_id,
        )

        if not self._fetcher.is_allowed(url):
            log.warning("robots.txt disallows %s; skipping profile %s", url, profile.name)
            return 0

        try:
            html = self._fetcher.fetch(url)
        except FetchError as exc:
            log.warning("fetch failed for profile %s: %s", profile.name, exc)
            return 0

        try:
            listings = parse_listings(
                html,
                include_topads=profile.include_topads,
                include_pro=profile.include_pro,
            )
        except Exception:
            log.exception("parser failed for profile %s", profile.name)
            return 0

        first_run = bootstrap or not self._storage.has_any_for_profile(profile.name)
        if first_run:
            log.info("first poll for profile %s — marking %d listings as seen, no notifications",
                     profile.name, len(listings))
            self._storage.mark_seen(profile.name, listings)
            return 0

        new = self._storage.filter_new(profile.name, listings)
        sent = 0
        for listing in new:
            try:
                self._notifier.send_listing(listing)
                sent += 1
            except Exception:
                log.exception("notify failed for listing %s in profile %s", listing.id, profile.name)
        # Mark all parsed listings as seen, not just newly notified — avoids re-trying failures forever.
        self._storage.mark_seen(profile.name, listings)
        if sent:
            log.info("profile %s: notified %d new listings", profile.name, sent)
        return sent

    def request_stop(self) -> None:
        self._stop_requested = True

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.request_stop())
        signal.signal(signal.SIGINT, lambda *_: self.request_stop())

    def run_until(self, *, deadline_iterations: int) -> None:
        """Polls every active profile up to deadline_iterations times. Used in tests + bootstrap mode."""
        active = [p for p in self._profiles if p.enabled]
        for _ in range(deadline_iterations):
            if self._stop_requested:
                return
            for profile in active:
                if self._stop_requested:
                    return
                self.poll_once(profile)

    def run_forever(self) -> None:
        active = [p for p in self._profiles if p.enabled]
        if not active:
            log.warning("no active profiles configured — exiting")
            return
        next_run: dict[str, float] = {p.name: time.monotonic() for p in active}
        log.info("starting main loop with %d active profile(s)", len(active))
        while not self._stop_requested:
            now = time.monotonic()
            due = [p for p in active if next_run[p.name] <= now]
            for profile in due:
                if self._stop_requested:
                    break
                self.poll_once(profile)
                next_run[profile.name] = time.monotonic() + profile.poll_interval_minutes * 60
            if self._stop_requested:
                break
            sleep_for = max(1.0, min(next_run.values()) - time.monotonic())
            time.sleep(min(sleep_for, 30.0))
        log.info("main loop stopped")
