from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from kleinanzeigen_watcher.cli import build_parser, cmd_run
from kleinanzeigen_watcher.logging_setup import setup_logging

FIXTURES = Path(__file__).parent / "fixtures"
ENV = {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kleinanzeigen_watcher.fetcher.time.sleep", lambda _: None)
    monkeypatch.setattr("kleinanzeigen_watcher.notifier.time.sleep", lambda _: None)
    monkeypatch.setattr("kleinanzeigen_watcher.scheduler.time.sleep", lambda _: None)


def _config(tmp_path: Path, *, profiles_yaml: str | None = None) -> Path:
    cfg = tmp_path / "config.yaml"
    body = profiles_yaml or """
profiles:
  - name: monitors
    query: office monitor
"""
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_cmd_run_bootstrap_marks_and_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    db_path = tmp_path / "ka.db"
    cfg = _config(tmp_path, profiles_yaml=f"""
defaults:
  db_path: {db_path}
profiles:
  - name: monitors
    query: office monitor
""")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(200, text=html)

    parser = build_parser()
    args = parser.parse_args(["run", "--config", str(cfg), "--bootstrap"])

    with patch("kleinanzeigen_watcher.cli.httpx.MockTransport", side_effect=httpx.MockTransport):
        rc = cmd_run(args, env=ENV, transport=httpx.MockTransport(handler))
    assert rc == 0
    # DB should now have rows for "monitors"
    import sqlite3
    cur = sqlite3.connect(str(db_path)).execute("SELECT COUNT(*) FROM seen_listings WHERE profile = ?", ("monitors",))
    count = cur.fetchone()[0]
    assert count > 0


def test_cmd_run_returns_nonzero_on_config_error(tmp_path: Path) -> None:
    bad_cfg = tmp_path / "config.yaml"
    bad_cfg.write_text("profiles:\n  - name: a\n", encoding="utf-8")  # missing query
    parser = build_parser()
    args = parser.parse_args(["run", "--config", str(bad_cfg), "--bootstrap"])
    rc = cmd_run(args, env=ENV)
    assert rc != 0


def test_setup_logging_attaches_stream_handler() -> None:
    root = logging.getLogger()
    initial_handlers = list(root.handlers)
    try:
        setup_logging(verbose=False, log_dir=None)
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    finally:
        # Restore original state
        root.handlers = initial_handlers


def test_cmd_run_once_polls_all_active_profiles_then_exits(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    db_path = tmp_path / "ka.db"
    cfg = _config(tmp_path, profiles_yaml=f"""
defaults:
  db_path: {db_path}
profiles:
  - name: a
    query: x
  - name: b
    query: y
""")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(200, text=html)

    parser = build_parser()
    args = parser.parse_args(["run", "--config", str(cfg), "--once"])
    rc = cmd_run(args, env=ENV, transport=httpx.MockTransport(handler))
    assert rc == 0
    # Both profiles should have been polled (first-run = silent bootstrap, marks all seen)
    import sqlite3
    counts = dict(
        sqlite3.connect(str(db_path)).execute(
            "SELECT profile, COUNT(*) FROM seen_listings GROUP BY profile"
        ).fetchall()
    )
    assert counts.get("a", 0) > 0
    assert counts.get("b", 0) > 0


def test_setup_logging_with_file_creates_rotating_handler(tmp_path: Path) -> None:
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    initial_handlers = list(root.handlers)
    try:
        setup_logging(verbose=True, log_dir=tmp_path)
        assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)
        # write a log line and check the file appears
        logging.getLogger("kleinanzeigen_watcher.test").info("hello")
        log_file = tmp_path / "kleinanzeigen-watcher.log"
        assert log_file.exists()
    finally:
        for h in list(root.handlers):
            if h not in initial_handlers:
                h.close()
                root.removeHandler(h)
