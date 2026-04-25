from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when a fetch ultimately fails (after retries)."""


_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}


class Fetcher:
    def __init__(
        self,
        *,
        user_agents: Iterable[str],
        min_delay_seconds: float = 5.0,
        timeout: float = 15.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._user_agents = list(user_agents)
        if not self._user_agents:
            raise ValueError("at least one user_agent required")
        self._min_delay = min_delay_seconds
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            http2=False,
        )
        self._last_request_at: float | None = None
        self._robots_cache: dict[str, RobotFileParser] = {}

    def fetch(self, url: str) -> str:
        self._respect_min_delay()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            headers = {**_DEFAULT_HEADERS, "User-Agent": random.choice(self._user_agents)}
            try:
                response = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("fetch error %s on attempt %d for %s", exc, attempt + 1, url)
                self._backoff(attempt)
                continue
            finally:
                self._last_request_at = time.monotonic()

            if response.status_code == 200:
                return response.text
            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", self._backoff_delay(attempt)))
                log.warning("429 on %s, sleeping %ss", url, retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                log.warning("server error %d on attempt %d for %s", response.status_code, attempt + 1, url)
                self._backoff(attempt)
                continue
            raise FetchError(f"non-retriable status {response.status_code} for {url}")

        raise FetchError(f"max retries exceeded for {url}: {last_exc}")

    def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(origin)
        if rp is None:
            rp = self._load_robots(origin)
            self._robots_cache[origin] = rp
        return rp.can_fetch("*", url)

    def close(self) -> None:
        self._client.close()

    def _respect_min_delay(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _backoff(self, attempt: int) -> None:
        time.sleep(self._backoff_delay(attempt))

    def _backoff_delay(self, attempt: int) -> float:
        return min(60.0, 2.0 ** attempt + random.uniform(0, 1))

    def _load_robots(self, origin: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            response = self._client.get(f"{origin}/robots.txt", headers=_DEFAULT_HEADERS)
            if response.status_code == 200:
                rp.parse(response.text.splitlines())
            else:
                log.warning("robots.txt fetch returned %d for %s; defaulting to allow", response.status_code, origin)
                rp.parse([])
        except httpx.HTTPError as exc:
            log.warning("robots.txt fetch failed for %s (%s); defaulting to allow", origin, exc)
            rp.parse([])
        return rp
