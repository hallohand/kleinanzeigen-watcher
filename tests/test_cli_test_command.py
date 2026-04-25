from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

from kleinanzeigen_watcher.cli import build_parser, cmd_test
from kleinanzeigen_watcher.fetcher import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kleinanzeigen_watcher.fetcher.time.sleep", lambda _: None)


def test_parser_accepts_test_subcommand_with_filters() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "test",
        "--query", "office monitor",
        "--plz", "01067",
        "--radius", "20",
    ])
    assert args.command == "test"
    assert args.query == "office monitor"
    assert args.plz == "01067"
    assert args.radius == 20


def test_cmd_test_fetches_parses_and_prints_listings() -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=html)

    fetcher = Fetcher(user_agents=["UA"], transport=httpx.MockTransport(handler))
    parser = build_parser()
    args = parser.parse_args(["test", "--query", "office monitor", "--max-results", "3"])
    out = io.StringIO()

    rc = cmd_test(args, fetcher=fetcher, stdout=out)

    assert rc == 0
    assert "/s-office-monitor/k0" in captured["url"]
    output = out.getvalue()
    # Three listings printed
    assert output.count("https://www.kleinanzeigen.de/s-anzeige/") == 3


def test_cmd_test_returns_nonzero_on_fetch_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    fetcher = Fetcher(user_agents=["UA"], transport=httpx.MockTransport(handler))
    parser = build_parser()
    args = parser.parse_args(["test", "--query", "x"])
    out = io.StringIO()

    rc = cmd_test(args, fetcher=fetcher, stdout=out)
    assert rc != 0
