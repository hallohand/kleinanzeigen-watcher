from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kleinanzeigen_watcher.fetcher import Fetcher, FetchError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kleinanzeigen_watcher.fetcher.time.sleep", lambda _: None)


def _mock_transport(handler: object) -> httpx.MockTransport:
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


def test_fetch_returns_body_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>ok</html>")

    f = Fetcher(user_agents=["UA1"], transport=_mock_transport(handler))
    assert f.fetch("https://www.kleinanzeigen.de/s-test/k0") == "<html>ok</html>"


def test_fetch_sets_user_agent_from_rotation() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, text="x")

    f = Fetcher(user_agents=["UA1", "UA2"], transport=_mock_transport(handler))
    f.fetch("https://www.kleinanzeigen.de/s-a/k0")
    f.fetch("https://www.kleinanzeigen.de/s-b/k0")
    assert set(seen) <= {"UA1", "UA2"}
    assert all(ua for ua in seen)


def test_fetch_sends_german_accept_language() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, text="x")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler))
    f.fetch("https://www.kleinanzeigen.de/s-a/k0")
    assert "de" in captured.get("accept-language", "").lower()


def test_fetch_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, text="rate limited")
        return httpx.Response(200, text="ok")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler), max_retries=3)
    assert f.fetch("https://www.kleinanzeigen.de/s-a/k0") == "ok"
    assert calls["n"] == 2


def test_fetch_retries_on_500_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="oops")
        return httpx.Response(200, text="ok")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler), max_retries=3)
    assert f.fetch("https://www.kleinanzeigen.de/s-a/k0") == "ok"
    assert calls["n"] == 3


def test_fetch_raises_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler), max_retries=2)
    with pytest.raises(FetchError):
        f.fetch("https://www.kleinanzeigen.de/s-a/k0")


def test_fetch_raises_on_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler))
    with pytest.raises(FetchError):
        f.fetch("https://www.kleinanzeigen.de/s-a/k0")


def test_fetch_enforces_min_delay_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("kleinanzeigen_watcher.fetcher.time.sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler), min_delay_seconds=5.0)
    f.fetch("https://www.kleinanzeigen.de/s-a/k0")
    sleeps.clear()
    f.fetch("https://www.kleinanzeigen.de/s-b/k0")
    assert sleeps and sleeps[-1] > 0


def test_robots_txt_blocks_disallowed_path() -> None:
    robots_txt = (FIXTURES / "robots.txt").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_txt)
        return httpx.Response(200, text="should not get here")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler))
    assert not f.is_allowed("https://www.kleinanzeigen.de/ad/12345")
    assert not f.is_allowed("https://www.kleinanzeigen.de/s-feed.rss")


def test_robots_txt_allows_search_paths() -> None:
    robots_txt = (FIXTURES / "robots.txt").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_txt)
        return httpx.Response(200, text="")

    f = Fetcher(user_agents=["UA"], transport=_mock_transport(handler))
    assert f.is_allowed("https://www.kleinanzeigen.de/s-office-monitor/k0")
    assert f.is_allowed("https://www.kleinanzeigen.de/s-01067/office-monitor/k0l1r20")
