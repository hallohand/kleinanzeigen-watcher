from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from kleinanzeigen_watcher.config import Profile
from kleinanzeigen_watcher.evaluator import Evaluator, Verdict
from kleinanzeigen_watcher.fetcher import Fetcher
from kleinanzeigen_watcher.notifier import Notifier
from kleinanzeigen_watcher.scheduler import Scheduler
from kleinanzeigen_watcher.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kleinanzeigen_watcher.fetcher.time.sleep", lambda _: None)
    monkeypatch.setattr("kleinanzeigen_watcher.notifier.time.sleep", lambda _: None)
    monkeypatch.setattr("kleinanzeigen_watcher.scheduler.time.sleep", lambda _: None)


def _profile(name: str = "p1", **overrides: object) -> Profile:
    base: dict = {"name": name, "query": "office monitor", "enabled": True}
    base.update(overrides)
    return Profile(**base)  # type: ignore[arg-type]


def _make_fetcher(html: str) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(200, text=html)

    return Fetcher(user_agents=["UA"], transport=httpx.MockTransport(handler))


def _make_failing_fetcher() -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    return Fetcher(user_agents=["UA"], transport=httpx.MockTransport(handler), max_retries=1)


def _make_scheduler(
    *,
    fetcher: Fetcher,
    storage: Storage,
    profiles: list[Profile] | None = None,
    evaluator: Evaluator | None = None,
) -> tuple[Scheduler, MagicMock]:
    notifier = MagicMock(spec=Notifier)
    sched = Scheduler(
        profiles=profiles or [_profile()],
        fetcher=fetcher,
        storage=storage,
        notifier=notifier,
        evaluator=evaluator,
    )
    return sched, notifier


def test_first_poll_marks_seen_no_notifications(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)

    sent = sched.poll_once(_profile())

    assert sent == 0
    notifier.send_listing.assert_not_called()
    assert storage.has_any_for_profile("p1") is True


def test_second_poll_with_no_new_sends_nothing(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)

    sched.poll_once(_profile())
    notifier.reset_mock()

    sent = sched.poll_once(_profile())
    assert sent == 0
    notifier.send_listing.assert_not_called()


def test_explicit_bootstrap_flag_marks_without_notifying(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)

    sent = sched.poll_once(_profile(), bootstrap=True)
    assert sent == 0
    notifier.send_listing.assert_not_called()
    assert storage.has_any_for_profile("p1") is True


def test_new_listings_notified_on_subsequent_poll(tmp_path: Path) -> None:
    html_first = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    # Simulate change: drop first article block to make it look "new" on second fetch
    # Easier: wipe db after bootstrap, then poll_once again with same html
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(fetcher=_make_fetcher(html_first), storage=storage)
    sched.poll_once(_profile(), bootstrap=True)
    notifier.reset_mock()

    # Pretend one specific listing is new: remove its row from storage so filter_new returns it.
    storage._conn.execute("DELETE FROM seen_listings WHERE id = ?", ("3391823696",))  # type: ignore[attr-defined]
    storage._conn.commit()  # type: ignore[attr-defined]

    sent = sched.poll_once(_profile())
    assert sent == 1
    assert notifier.send_listing.call_count == 1
    sent_listing = notifier.send_listing.call_args[0][0]
    assert sent_listing.id == "3391823696"


def test_fetch_error_does_not_crash(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(fetcher=_make_failing_fetcher(), storage=storage)

    sent = sched.poll_once(_profile())
    assert sent == 0
    notifier.send_listing.assert_not_called()


def test_disabled_profile_skipped_in_run_until(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, notifier = _make_scheduler(
        fetcher=_make_fetcher(html),
        storage=storage,
        profiles=[_profile(name="active"), _profile(name="paused", enabled=False)],
    )

    sched.run_until(deadline_iterations=1)
    # Only active profile should have been polled
    assert storage.has_any_for_profile("active") is True
    assert storage.has_any_for_profile("paused") is False


def test_run_until_polls_each_active_profile_once(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, _ = _make_scheduler(
        fetcher=_make_fetcher(html),
        storage=storage,
        profiles=[_profile(name="a"), _profile(name="b")],
    )

    sched.run_until(deadline_iterations=2)
    assert storage.has_any_for_profile("a") is True
    assert storage.has_any_for_profile("b") is True


def test_request_stop_wakes_run_forever_immediately(tmp_path: Path) -> None:
    import threading
    import time as real_time

    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    sched, _ = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)

    t = threading.Thread(target=sched.run_forever, daemon=True)
    t.start()
    real_time.sleep(0.5)  # let it enter the wait()
    start = real_time.monotonic()
    sched.request_stop()
    t.join(timeout=3.0)
    elapsed = real_time.monotonic() - start

    assert not t.is_alive(), "run_forever did not stop"
    assert elapsed < 1.0, f"stop took {elapsed:.2f}s — should be near-instant"


def test_evaluator_called_only_when_profile_ai_filter_true(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    evaluator = MagicMock(spec=Evaluator)
    evaluator.evaluate.return_value = Verdict(recommended=True, reason="ok")

    sched, notifier = _make_scheduler(
        fetcher=_make_fetcher(html), storage=storage,
        profiles=[_profile(ai_filter=False)],
        evaluator=evaluator,
    )
    sched.poll_once(_profile(ai_filter=False), bootstrap=True)
    storage._conn.execute("DELETE FROM seen_listings WHERE id = ?", ("3391823696",))  # type: ignore[attr-defined]
    storage._conn.commit()  # type: ignore[attr-defined]
    notifier.reset_mock()

    sched.poll_once(_profile(ai_filter=False))

    evaluator.evaluate.assert_not_called()
    assert notifier.send_listing.call_count == 1


def test_evaluator_filters_out_non_recommended_listings(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    evaluator = MagicMock(spec=Evaluator)
    # evaluate returns False for all listings
    evaluator.evaluate.return_value = Verdict(recommended=False, reason="zu klein")

    sched, notifier = _make_scheduler(
        fetcher=_make_fetcher(html), storage=storage,
        profiles=[_profile(ai_filter=True)], evaluator=evaluator,
    )
    sched.poll_once(_profile(ai_filter=True), bootstrap=True)
    storage._conn.execute("DELETE FROM seen_listings WHERE id = ?", ("3391823696",))  # type: ignore[attr-defined]
    storage._conn.commit()  # type: ignore[attr-defined]
    notifier.reset_mock()
    evaluator.evaluate.reset_mock()

    sent = sched.poll_once(_profile(ai_filter=True))

    assert sent == 0
    evaluator.evaluate.assert_called_once()
    notifier.send_listing.assert_not_called()


def test_evaluator_passes_reason_to_notifier_for_recommended(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    evaluator = MagicMock(spec=Evaluator)
    evaluator.evaluate.return_value = Verdict(recommended=True, reason="Dell, 24 Zoll, FullHD")

    sched, notifier = _make_scheduler(
        fetcher=_make_fetcher(html), storage=storage,
        profiles=[_profile(ai_filter=True)], evaluator=evaluator,
    )
    sched.poll_once(_profile(ai_filter=True), bootstrap=True)
    storage._conn.execute("DELETE FROM seen_listings WHERE id = ?", ("3391823696",))  # type: ignore[attr-defined]
    storage._conn.commit()  # type: ignore[attr-defined]
    notifier.reset_mock()

    sched.poll_once(_profile(ai_filter=True))

    notifier.send_listing.assert_called_once()
    kwargs = notifier.send_listing.call_args.kwargs
    assert kwargs.get("verdict_reason") == "Dell, 24 Zoll, FullHD"


def test_verdicts_persisted_to_storage(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    evaluator = MagicMock(spec=Evaluator)
    # First call returns recommended True, rest False
    evaluator.evaluate.side_effect = lambda lst: (
        Verdict(recommended=True, reason="ja " + lst.id) if lst.id == "3391823696"
        else Verdict(recommended=False, reason="nein")
    )

    sched, _ = _make_scheduler(
        fetcher=_make_fetcher(html), storage=storage,
        profiles=[_profile(ai_filter=True)], evaluator=evaluator,
    )
    # bootstrap=True triggers eval+persist via the new evaluate-during-bootstrap path
    sched.poll_once(_profile(ai_filter=True), bootstrap=True, evaluate_during_bootstrap=True)

    top = storage.get_top_recommended("p1", limit=10)
    assert len(top) == 1
    assert top[0][0].id == "3391823696"
    assert "ja 3391823696" in top[0][1]


def test_non_recommended_still_marked_seen_to_avoid_re_evaluation(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")
    evaluator = MagicMock(spec=Evaluator)
    evaluator.evaluate.return_value = Verdict(recommended=False, reason="no")

    sched, _ = _make_scheduler(
        fetcher=_make_fetcher(html), storage=storage,
        profiles=[_profile(ai_filter=True)], evaluator=evaluator,
    )
    sched.poll_once(_profile(ai_filter=True), bootstrap=True)
    storage._conn.execute("DELETE FROM seen_listings WHERE id = ?", ("3391823696",))  # type: ignore[attr-defined]
    storage._conn.commit()  # type: ignore[attr-defined]
    evaluator.evaluate.reset_mock()

    sched.poll_once(_profile(ai_filter=True))
    sched.poll_once(_profile(ai_filter=True))

    # Second poll_once should NOT call evaluator again — listing already seen
    assert evaluator.evaluate.call_count == 1


def test_topad_filtering_respects_profile_setting(tmp_path: Path) -> None:
    html = (FIXTURES / "srp_simple.html").read_text(encoding="utf-8")
    storage = Storage(tmp_path / "db")

    # First profile excludes topads (default)
    sched, _ = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)
    sched.poll_once(_profile(name="default"))
    cur = storage._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM seen_listings WHERE profile = ?", ("default",)
    )
    default_count = cur.fetchone()[0]

    sched, _ = _make_scheduler(fetcher=_make_fetcher(html), storage=storage)
    sched.poll_once(_profile(name="with_topads", include_topads=True))
    cur = storage._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM seen_listings WHERE profile = ?", ("with_topads",)
    )
    topad_count = cur.fetchone()[0]

    assert topad_count > default_count
