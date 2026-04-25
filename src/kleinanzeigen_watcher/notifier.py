from __future__ import annotations

import html
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from ._retry import exp_backoff

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

    def send_listing(self, listing: Listing, *, verdict_reason: str | None = None) -> None:
        text = self._format(listing, verdict_reason=verdict_reason)
        if listing.image_url:
            try:
                self._post("sendPhoto", {
                    "chat_id": self._chat_id,
                    "photo": listing.image_url,
                    "caption": text,
                    "parse_mode": "HTML",
                })
                return
            except NotifierError as exc:
                log.warning("sendPhoto failed (%s), falling back to sendMessage", exc)
        self.send_html(text)

    def send_html(self, text: str, *, disable_preview: bool = False) -> None:
        """Send a free-form HTML-formatted message. Used by digest commands."""
        self._post("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        })

    def close(self) -> None:
        self._client.close()

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_BASE}/bot{self._token}/{method}"
        last_failure: str = "no attempts made"
        for attempt in range(self._max_retries):
            try:
                response = self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last_failure = f"{type(exc).__name__}: {exc}"
                time.sleep(exp_backoff(attempt))
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                retry_after = self._extract_retry_after(response)
                last_failure = f"HTTP 429 (Retry-After: {retry_after}s)"
                log.warning("telegram 429, sleeping %ss", retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                last_failure = f"HTTP {response.status_code}"
                log.warning("telegram %d on attempt %d", response.status_code, attempt + 1)
                time.sleep(exp_backoff(attempt))
                continue
            raise NotifierError(f"telegram {method} returned {response.status_code}: {response.text[:200]}")

        raise NotifierError(f"telegram {method} failed after {self._max_retries} retries (last: {last_failure})")

    @staticmethod
    def _extract_retry_after(response: httpx.Response) -> float:
        try:
            body = response.json()
            return float(body.get("parameters", {}).get("retry_after", 5))
        except ValueError:
            return float(response.headers.get("retry-after", 5))

    @staticmethod
    def _format(listing: Listing, *, verdict_reason: str | None = None) -> str:
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
        if verdict_reason:
            parts.append(f"🤖 {html.escape(verdict_reason)}")
        if desc:
            parts.append(desc)
        parts.append(f'<a href="{listing.url}">Anzeige öffnen</a>')
        return "\n".join(parts)


class NotifierError(Exception):
    """Raised when a Telegram send ultimately fails (after retries or on non-retriable status)."""
