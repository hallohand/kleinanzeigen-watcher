from __future__ import annotations

import html
import logging
import random
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .parser import Listing

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DESCRIPTION_LIMIT = 200


class Notifier:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        max_retries: int = 3,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def send_listing(self, listing: Listing) -> None:
        text = self._format(listing)
        if listing.image_url:
            try:
                self._post("sendPhoto", {
                    "chat_id": self._chat_id,
                    "photo": listing.image_url,
                    "caption": text,
                    "parse_mode": "HTML",
                })
                return
            except _NotifierError as exc:
                log.warning("sendPhoto failed (%s), falling back to sendMessage", exc)
        self._post("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })

    def close(self) -> None:
        self._client.close()

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_BASE}/bot{self._token}/{method}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                retry_after = self._extract_retry_after(response)
                log.warning("telegram 429, sleeping %ss", retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                log.warning("telegram %d on attempt %d", response.status_code, attempt + 1)
                self._sleep_backoff(attempt)
                continue
            raise _NotifierError(f"telegram {method} returned {response.status_code}: {response.text[:200]}")

        raise _NotifierError(f"telegram {method} failed after {self._max_retries} retries: {last_exc}")

    @staticmethod
    def _extract_retry_after(response: httpx.Response) -> float:
        try:
            body = response.json()
            return float(body.get("parameters", {}).get("retry_after", 5))
        except ValueError:
            return float(response.headers.get("retry-after", 5))

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(60.0, 2.0 ** attempt + random.uniform(0, 1)))

    @staticmethod
    def _format(listing: Listing) -> str:
        title = html.escape(listing.title or "(ohne Titel)")
        price = html.escape(listing.price or "")
        location = html.escape(listing.location or "")
        if listing.distance:
            location = f"{location} ({html.escape(listing.distance)})" if location else html.escape(listing.distance)
        desc = html.escape((listing.description or "")[:DESCRIPTION_LIMIT])
        meta_line = " | ".join(part for part in (price, location) if part)
        parts = [f"<b>{title}</b>"]
        if meta_line:
            parts.append(meta_line)
        if desc:
            parts.append(desc)
        parts.append(f'<a href="{listing.url}">Anzeige öffnen</a>')
        return "\n".join(parts)


class _NotifierError(Exception):
    pass
