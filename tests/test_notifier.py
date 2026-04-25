from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from kleinanzeigen_watcher.notifier import Notifier
from kleinanzeigen_watcher.parser import Listing


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kleinanzeigen_watcher.notifier.time.sleep", lambda _: None)


def _listing(image_url: str | None = None, title: str = "Office Monitor") -> Listing:
    return Listing(
        id="1234567",
        title=title,
        url="https://www.kleinanzeigen.de/s-anzeige/x/1234567",
        price="55 € VB",
        location="01067 Dresden",
        description="HP Office Monitor 24 Zoll",
        image_url=image_url,
        posted_at=datetime(2026, 4, 25, 19, 31),
        is_topad=False,
        is_pro=False,
    )


def _ok_response() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {}})


def test_send_listing_without_image_calls_sendMessage() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing(image_url=None))

    assert len(calls) == 1
    path, body = calls[0]
    assert path == "/botT/sendMessage"
    assert body["chat_id"] == "42"
    assert body["parse_mode"] == "HTML"
    assert "Office Monitor" in body["text"]
    assert body["text"].count("<a") == 1


def test_send_listing_with_image_calls_sendPhoto() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing(image_url="https://img.kleinanzeigen.de/x.jpg"))

    assert len(calls) == 1
    path, body = calls[0]
    assert path == "/botT/sendPhoto"
    assert body["photo"] == "https://img.kleinanzeigen.de/x.jpg"
    assert "Office Monitor" in body["caption"]


def test_send_listing_falls_back_to_text_when_photo_fails() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("sendPhoto"):
            return httpx.Response(400, json={"ok": False, "description": "wrong file"})
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing(image_url="https://img.kleinanzeigen.de/broken.jpg"))

    assert len(calls) == 2
    assert calls[0][0].endswith("sendPhoto")
    assert calls[1][0].endswith("sendMessage")


def test_429_retries_with_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 2}})
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing())
    assert calls["n"] == 2


def test_500_retries_with_backoff() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler), max_retries=3)
    n.send_listing(_listing())
    assert calls["n"] == 3


def test_html_special_chars_escaped_in_title() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing(title="Monitor < 24 inch & cheap >"))

    text = captured.get("text", "")
    assert "&lt;" in text and "&gt;" in text and "&amp;" in text
    assert "<b>" in text  # our own tags survive


def test_url_used_as_anchor_in_text() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response()

    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(_listing())

    assert 'href="https://www.kleinanzeigen.de/s-anzeige/x/1234567"' in captured["text"]


def test_distance_included_in_message_when_present() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response()

    listing = Listing(
        id="1", title="t", url="u", price="5 €", location="01067 Dresden",
        description="", image_url=None, posted_at=None,
        is_topad=False, is_pro=False, distance="11 km",
    )
    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(listing)
    assert "11 km" in captured["text"]


def test_description_truncated_to_200_chars() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response()

    long_desc = "x" * 500
    listing = Listing(
        id="1", title="t", url="u", price="p", location="l",
        description=long_desc, image_url=None, posted_at=None,
        is_topad=False, is_pro=False,
    )
    n = Notifier(bot_token="T", chat_id="42", transport=httpx.MockTransport(handler))
    n.send_listing(listing)
    assert "x" * 500 not in captured["text"]
    assert "x" * 200 in captured["text"]
