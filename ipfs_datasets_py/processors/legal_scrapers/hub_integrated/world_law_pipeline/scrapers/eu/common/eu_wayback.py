"""EU-lane wrapper around the shared ArchiveFetcher (2026-10-18; v3 12:1x PT for the shared deferral API).

The shared fetcher (pipeline/archive, README 'Errors, deferrals') owns throttling: 429/5xx -> no in-process retry, box-wide
per-host cool-down (Retry-After or 60 s doubling to 900 s), ArchiveDeferred(.not_before, .families, .hosts); fetch_best /
fetch_newest RAISE a merged ArchiveDeferred when nothing usable was found and a source was throttled (None = genuine miss);
cc_captures / list_captures return a CaptureList flagged .truncated/.deferral; timeouts get at most 1 retry; lanes >= 5 s apart.

EU-only, kept: ONE EU Wayback request in flight across ALL EU processes (flock _state/archive/eu_wayback.lock, SIGTERM-aware).
Dropped in v3 (now redundant): max_retries=1 override (shared timeout_retries=1), wb_not_before / wb_paused() post-item
cool-down polling (deferrals are raised now; loops requeue items for e.not_before and pause a target on Wayback deferrals).
Helpers: deferred_until(e), is_wayback_deferral(e), gate_status() (shared web.archive.org cool-down, for runner.json).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import contextlib
import errno
import fcntl
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ["ARCHIVE_LANE"] = "eu"            # lane for anything in this process that reads $ARCHIVE_LANE
from archive import ArchiveFetcher  # noqa: E402
from archive.core import ArchiveTransient  # noqa: E402
try:
    from archive.core import ArchiveDeferred  # noqa: E402  (shared deferral, 2026-10-18 ~12:00 PT)
    from archive import deferral as _deferral  # noqa: E402
except ImportError:                           # older shared module: nothing raises it
    class ArchiveDeferred(ArchiveTransient):  # type: ignore[no-redef]
        not_before = 0.0
    _deferral = None

LANE = "eu"
WB_HOST = "web.archive.org"
STATE_DIR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/archive"))
LOCK = STATE_DIR / "eu_wayback.lock"
log = logging.getLogger("archive_jobs")
_tlock = threading.Lock()


def wb_cooldown_until() -> float:
    """Epoch when the shared box-wide cool-down of web.archive.org ends (0 if none)."""
    if _deferral is None:
        return 0.0
    left = _deferral.host_cooldown(WB_HOST)
    return time.time() + left if left > 0 else 0.0


def gate_status() -> dict:
    """For runner.json: the shared cool-down entry of web.archive.org."""
    if _deferral is None:
        return {"shared_deferral": False}
    h = dict(_deferral.host_status().get(WB_HOST) or {})
    h["cooldown_left_s"] = round(_deferral.host_cooldown(WB_HOST))
    return h


def deferred_until(e: BaseException) -> float:
    """not_before of an ArchiveDeferred (0 for other errors)."""
    return float(getattr(e, "not_before", 0) or 0) if isinstance(e, ArchiveDeferred) else 0.0


@contextlib.contextmanager
def _eu_slot(stop: Callable[[], bool]):
    """One EU Wayback request at a time across all EU processes (and threads)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _tlock:
        fd = os.open(str(LOCK), os.O_RDWR | os.O_CREAT, 0o666)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                if stop():
                    raise ArchiveTransient("eu wayback: stop requested while waiting for the EU lane slot")
                time.sleep(0.5)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def is_wayback_deferral(e: BaseException) -> bool:
    """True if a (merged) ArchiveDeferred involves Wayback (family 'wayback' or host web.archive.org)."""
    if not isinstance(e, ArchiveDeferred):
        return False
    fams = set(getattr(e, "families", None) or [getattr(e, "family", "")])
    hosts = set(getattr(e, "hosts", None) or [getattr(e, "host", "")])
    return "wayback" in fams or WB_HOST in hosts


class EUArchiveFetcher(ArchiveFetcher):
    """ArchiveFetcher for lane eu: shared limiter/breaker/deferral + EU single in-flight Wayback lock. stop(): SIGTERM flag."""

    def __init__(self, *a, stop: Optional[Callable[[], bool]] = None, **kw):
        kw["lane"] = LANE
        super().__init__(*a, **kw)
        self.stop = stop or (lambda: False)

    def _get(self, family, url, **kw):
        if family != "wayback":
            return super()._get(family, url, **kw)
        with _eu_slot(self.stop):
            return super()._get(family, url, **kw)
