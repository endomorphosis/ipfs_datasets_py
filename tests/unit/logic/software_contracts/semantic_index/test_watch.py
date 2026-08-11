"""Tests for the hermetic notification-only semantic-index watcher."""

from __future__ import annotations

import threading
import time

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index.watch import (
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

    def callback(notification: WatchNotification) -> None:
        invoked.set()
        raise RuntimeError("callback failure")

    watch = watch_repository(tmp_path, callback, debounce_ms=10)
    source.write_text("value = 2\n", encoding="utf-8")
    _wait_for(invoked)
    deadline = time.monotonic() + 1.0
    while watch.last_callback_error is None and time.monotonic() < deadline:
        time.sleep(0.01)
    watch.stop()

    assert isinstance(watch.last_callback_error, RuntimeError)
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
