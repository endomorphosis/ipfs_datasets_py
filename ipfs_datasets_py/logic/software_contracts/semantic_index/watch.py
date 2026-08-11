"""Debounced, notification-only repository watching.

This module deliberately has no watcher-backend dependency.  It periodically
asks the canonical scanner for a fresh state, so operating-system events are
only an optional wake-up hint and can neither establish state nor affect the
result.  In particular, a missed event or an atomic rename is corrected by the
next polling scan.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time
from typing import Callable

from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    RepositoryScanner,
)


WATCH_SCHEMA = "ipfs-datasets.software-contracts.semantic-index-watch@1"


class RepositoryWatchError(ValueError):
    """Raised when a repository watch request is invalid."""


@dataclass(frozen=True, slots=True)
class WatchNotification:
    """A debounced canonical-state update delivered to a watcher callback.

    ``state`` is always the result of a new :class:`RepositoryScanner` scan;
    it is never reconstructed from filesystem-event paths.  ``previous_state``
    is the state from the last successfully delivered notification (or the
    baseline captured when the watch started).  Delta and invalidation planning
    deliberately remain separate operations until their canonical producers
    are available.
    """

    state: RepositoryState
    previous_state: RepositoryState

    def __post_init__(self) -> None:
        if not isinstance(self.state, RepositoryState):
            raise TypeError("state must be a RepositoryState")
        if not isinstance(self.previous_state, RepositoryState):
            raise TypeError("previous_state must be a RepositoryState")
        if self.state.repository_id != self.previous_state.repository_id:
            raise RepositoryWatchError("notification states must share a repository_id")

    @property
    def state_cid(self) -> str:
        """CID of the newly scanned state."""
        return self.state.state_cid

    @property
    def previous_state_cid(self) -> str:
        """CID of the previously delivered state."""
        return self.previous_state.state_cid


class RepositoryWatch:
    """Own a polling watcher thread and its explicit lifecycle.

    Call :meth:`start` once, then :meth:`stop` (or use the context-manager
    protocol).  Callback exceptions are retained in ``last_callback_error``
    and do not terminate or escape the worker thread.  ``notify`` is public
    for an optional event backend: it merely wakes the polling loop and never
    carries event paths or changes the scanner result.
    """

    def __init__(
        self,
        repository: str | os.PathLike[str],
        callback: Callable[[WatchNotification], object],
        *,
        debounce_ms: int = 250,
        poll_interval_ms: int | None = None,
        scanner: RepositoryScanner | None = None,
    ) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        if type(debounce_ms) is not int or debounce_ms < 0:
            raise RepositoryWatchError("debounce_ms must be a nonnegative integer")
        if poll_interval_ms is not None and (type(poll_interval_ms) is not int or poll_interval_ms < 1):
            raise RepositoryWatchError("poll_interval_ms must be a positive integer or None")
        if scanner is not None and not isinstance(scanner, RepositoryScanner):
            raise TypeError("scanner must be a RepositoryScanner or None")

        self.repository = Path(repository).resolve()
        if not self.repository.is_dir():
            raise RepositoryWatchError("repository must be an existing directory")
        self.callback = callback
        self.debounce_ms = debounce_ms
        # A short bounded cadence makes polling responsive while preventing a
        # zero-debounce configuration from becoming a busy loop.
        self.poll_interval_ms = poll_interval_ms or max(10, min(100, debounce_ms or 10))
        self.scanner = scanner or RepositoryScanner()
        self.current_state: RepositoryState | None = None
        self.last_callback_error: BaseException | None = None
        self.last_scan_error: Exception | None = None
        self._stopped = threading.Event()
        self._wakeup = threading.Event()
        self._started = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Whether the worker thread is alive."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> "RepositoryWatch":
        """Capture a baseline state and begin polling for a changed state."""
        with self._lock:
            if self._stopped.is_set():
                raise RepositoryWatchError("a stopped watch cannot be restarted")
            if self._started:
                raise RepositoryWatchError("watch has already been started")
            # This is the first canonical snapshot, not an update notification.
            self.current_state = self.scanner.scan(self.repository)
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                name="semantic-index-repository-watch",
                daemon=True,
            )
            self._thread.start()
        return self

    def notify(self) -> None:
        """Wake a scan early; callers must not treat this as state authority."""
        if not self._stopped.is_set():
            self._wakeup.set()

    def stop(self) -> None:
        """Request shutdown and join the worker unless called by that worker."""
        self._stopped.set()
        self._wakeup.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    close = stop

    def __enter__(self) -> "RepositoryWatch":
        return self if self._started else self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

    def _scan(self) -> RepositoryState | None:
        try:
            # ``current_state`` is only an optimization for the scanner; scan
            # still obtains a complete fresh snapshot before producing state.
            return self.scanner.scan(self.repository, previous_state=self.current_state)
        except Exception as exc:
            self.last_scan_error = exc
            return None

    def _wait(self, seconds: float) -> None:
        self._wakeup.wait(seconds)
        self._wakeup.clear()

    def _run(self) -> None:
        assert self.current_state is not None
        candidate: RepositoryState | None = None
        candidate_since = 0.0
        poll_seconds = self.poll_interval_ms / 1000.0
        debounce_seconds = self.debounce_ms / 1000.0
        while not self._stopped.is_set():
            scanned = self._scan()
            if scanned is not None:
                self.last_scan_error = None
                current = self.current_state
                assert current is not None
                if scanned.state_cid == current.state_cid:
                    candidate = None
                elif candidate is None or scanned.state_cid != candidate.state_cid:
                    candidate = scanned
                    candidate_since = time.monotonic()
                elif time.monotonic() - candidate_since >= debounce_seconds:
                    notification = WatchNotification(scanned, current)
                    # Advance before invoking user code.  A throwing callback
                    # must not repeatedly receive the same update forever.
                    self.current_state = scanned
                    candidate = None
                    try:
                        self.callback(notification)
                    except BaseException as exc:
                        self.last_callback_error = exc

            wait_seconds = poll_seconds
            if candidate is not None:
                remaining = debounce_seconds - (time.monotonic() - candidate_since)
                wait_seconds = min(wait_seconds, max(0.0, remaining))
            self._wait(wait_seconds)


def watch_repository(
    repo_path: str | os.PathLike[str],
    callback: Callable[[WatchNotification], object],
    *,
    debounce_ms: int = 250,
) -> RepositoryWatch:
    """Start a repository watch and return its lifecycle handle.

    The polling implementation is hermetic: it starts no daemon, makes no
    network request, and imports no optional watcher package.
    """
    return RepositoryWatch(repo_path, callback, debounce_ms=debounce_ms).start()


__all__ = [
    "WATCH_SCHEMA",
    "RepositoryWatchError",
    "WatchNotification",
    "RepositoryWatch",
    "watch_repository",
]
