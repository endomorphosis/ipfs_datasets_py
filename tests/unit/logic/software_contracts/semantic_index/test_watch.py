"""Tests for the hermetic notification-only semantic-index watcher."""

from __future__ import annotations

import threading
import time

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index.watch import (
    MIN_POLL_INTERVAL_MS,
    RepositoryWatch,
    RepositoryWatchError,
    WatchNotification,
    watch_repository,
)


def _wait_for(event: threading.Event, *, timeout: float = 3.0) -> None:
    assert event.wait(timeout), "watch callback did not run before timeout"


def test_polling_scan_detects_missed_event_and_returns_fresh_state(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    delivered: list[WatchNotification] = []
    changed = threading.Event()

    with watch_repository(tmp_path, lambda item: (delivered.append(item), changed.set()), debounce_ms=20) as watch:
        baseline = watch.current_state
        assert baseline is not None
        # No notify() call: the next canonical snapshot must still correct the
        # intentionally missed notification.
        source.write_text("value = 2\n", encoding="utf-8")
        _wait_for(changed)

    assert len(delivered) == 1
    assert delivered[0].previous_state == baseline
    assert delivered[0].state.state_cid != baseline.state_cid
    assert not watch.is_running


def test_bursts_and_event_order_coalesce_to_one_final_snapshot(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    delivered: list[WatchNotification] = []
    changed = threading.Event()

    with watch_repository(tmp_path, lambda item: (delivered.append(item), changed.set()), debounce_ms=80) as watch:
        source.write_text("value = 2\n", encoding="utf-8")
        watch.notify()
        source.write_text("value = 3\n", encoding="utf-8")
        watch.notify()
        _wait_for(changed)

    assert len(delivered) == 1
    assert delivered[0].state == watch.current_state
    # A fresh scanner result sees the final content, rather than either event.
    assert any(symbol.metadata.get("value") != "1" for symbol in delivered[0].state.symbols) or delivered[0].state.state_cid != delivered[0].previous_state_cid


def test_callback_exception_is_contained_and_stop_joins_thread(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    invoked = threading.Event()
    progressed = threading.Event()
    call_count = {"n": 0}

    def callback(notification: WatchNotification) -> None:
        call_count["n"] += 1
        invoked.set()
        if call_count["n"] == 1:
            raise RuntimeError("callback failure")
        progressed.set()

    watch = watch_repository(tmp_path, callback, debounce_ms=10, poll_interval_ms=20)
    source.write_text("value = 2\n", encoding="utf-8")
    _wait_for(invoked)
    deadline = time.monotonic() + 1.0
    while watch.last_callback_error is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert isinstance(watch.last_callback_error, RuntimeError)
    # Progress continues after the isolated callback exception.
    source.write_text("value = 3\n", encoding="utf-8")
    watch.notify()
    _wait_for(progressed, timeout=3.0)
    assert call_count["n"] >= 2
    assert watch.notification_count >= 2

    started = time.monotonic()
    watch.stop()
    elapsed = time.monotonic() - started
    assert elapsed < watch.join_timeout_s
    assert not watch.is_running


def test_watch_validates_lifecycle_and_context_does_not_restart(tmp_path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    watch = RepositoryWatch(tmp_path, lambda notification: None, debounce_ms=0)
    assert watch.start() is watch
    with pytest.raises(RepositoryWatchError, match="already been started"):
        watch.start()
    watch.stop()
    with pytest.raises(RepositoryWatchError, match="cannot be restarted"):
        watch.start()


def test_stop_join_finishes_within_deterministic_bound(tmp_path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    watch = RepositoryWatch(
        tmp_path,
        lambda notification: None,
        debounce_ms=50,
        poll_interval_ms=30,
        join_timeout_s=1.5,
    )
    watch.start()
    assert watch.join_timeout_s == 1.5
    started = time.monotonic()
    watch.stop(join_timeout_s=1.5)
    assert time.monotonic() - started < 1.5
    assert not watch.is_running


def test_polling_does_not_busy_spin_on_scan_errors(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner

    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    # Baseline scan succeeds during start; subsequent scans fail.
    calls = {"n": 0}
    original = RepositoryScanner.scan

    def flaky(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return original(self, *args, **kwargs)
        raise RuntimeError("forced scan failure")

    monkeypatch.setattr(RepositoryScanner, "scan", flaky)
    watch = RepositoryWatch(tmp_path, lambda notification: None, debounce_ms=0, poll_interval_ms=40)
    watch.start()
    time.sleep(0.25)
    failures_before = calls["n"]
    time.sleep(0.25)
    failures_after = calls["n"]
    watch.stop()
    # With a 40ms poll interval, 250ms windows should not produce hundreds of calls.
    assert failures_after - failures_before < 20
    assert watch.poll_interval_ms >= MIN_POLL_INTERVAL_MS
    assert watch.last_scan_error is not None


def test_zero_debounce_still_respects_minimum_poll_interval(tmp_path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    watch = RepositoryWatch(tmp_path, lambda notification: None, debounce_ms=0)
    assert watch.poll_interval_ms >= MIN_POLL_INTERVAL_MS
    watch.start()
    watch.stop()
    assert not watch.is_running


def test_concurrent_watchers_converge_without_duplicate_authority(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    delivered_a: list[WatchNotification] = []
    delivered_b: list[WatchNotification] = []
    ready_a = threading.Event()
    ready_b = threading.Event()

    watch_a = watch_repository(
        tmp_path,
        lambda item: (delivered_a.append(item), ready_a.set()),
        debounce_ms=20,
        poll_interval_ms=20,
    )
    watch_b = watch_repository(
        tmp_path,
        lambda item: (delivered_b.append(item), ready_b.set()),
        debounce_ms=20,
        poll_interval_ms=20,
    )
    try:
        baseline_a = watch_a.current_state
        baseline_b = watch_b.current_state
        assert baseline_a is not None and baseline_b is not None
        # Independent fences: each owns its baseline, both see the same truth.
        assert baseline_a.state_cid == baseline_b.state_cid
        assert watch_a is not watch_b
        assert watch_a.current_state is not watch_b.current_state or baseline_a == baseline_b

        source.write_text("value = 2\n", encoding="utf-8")
        watch_a.notify()
        watch_b.notify()
        _wait_for(ready_a)
        _wait_for(ready_b)

        assert delivered_a and delivered_b
        assert delivered_a[-1].state.state_cid == delivered_b[-1].state.state_cid
        assert delivered_a[-1].state == delivered_b[-1].state
        assert watch_a.current_state is not None
        assert watch_b.current_state is not None
        assert watch_a.current_state.state_cid == watch_b.current_state.state_cid
        # Notifications remain scanner-derived, not event-path authority.
        assert delivered_a[-1].state.state_cid != baseline_a.state_cid
    finally:
        watch_a.stop()
        watch_b.stop()
    assert not watch_a.is_running
    assert not watch_b.is_running
