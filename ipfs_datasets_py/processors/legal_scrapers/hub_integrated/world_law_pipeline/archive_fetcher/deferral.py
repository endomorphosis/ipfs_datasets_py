"""Throttle deferral for the shared ArchiveFetcher (2026-10-18).

On HTTP 429 / 5xx the fetcher no longer retries the same URL in-process. It records a box-wide per-host
cool-down and raises ArchiveDeferred (a subclass of ArchiveTransient, so existing `except ArchiveTransient`
handlers keep working); the caller should requeue the item and move on.

Cool-down per host: Retry-After (delta-seconds or HTTP-date) when present, else 60 s doubling per consecutive
deferral on that host, capped at 900 s; a successful response from the host resets it.
Per-lane spacing: >= LANE_MIN_INTERVAL s (default 5, env WORLD_LAW_LANE_MIN_INTERVAL) between request starts of
one lane for the spaced families (default wayback; env WORLD_LAW_LANE_SPACED_FAMILIES="wayback,cc_index,cc_data").
State is box-wide / cross-process: JSON files + flock under ratelimit.RATE_DIR.
Deferrals are NOT recorded as Wayback circuit-breaker failures (timeouts / network errors still are).
"""
from __future__ import annotations

import contextlib
import email.utils
import fcntl
import json
import math
import os
import re
import time
from datetime import timezone
from pathlib import Path
from typing import Optional

from . import ratelimit

COOL_BASE = 60.0
COOL_MAX = 900.0
RA_MAX = 6 * 3600.0
LANE_MIN_INTERVAL = float(os.environ.get("WORLD_LAW_LANE_MIN_INTERVAL", "5"))
LANE_SPACED_FAMILIES = frozenset(f.strip() for f in os.environ.get("WORLD_LAW_LANE_SPACED_FAMILIES", "wayback").split(",")
                                 if f.strip())
_sleep = time.sleep   # patched by tests
_now = time.time


def parse_retry_after(v: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """RFC 9110 Retry-After -> seconds to wait (>= 0, clamped to 6 h), None if absent/unparseable."""
    if not v:
        return None
    v = str(v).strip()
    try:
        s = float(v)
        return min(RA_MAX, max(0.0, s)) if math.isfinite(s) else None
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return min(RA_MAX, max(0.0, dt.timestamp() - (now if now is not None else _now())))


def _dir() -> Path:
    d = Path(ratelimit.RATE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextlib.contextmanager
def _locked_json(name: str):
    d = _dir()
    fd = os.open(str(d / f"{name}.lock"), os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = d / f"{name}.json"
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        yield data
        tmp = d / f".{name}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, indent=1, default=str))
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# -- per-host cool-down ------------------------------------------------------------------------------
def host_cooldown(host: str) -> float:
    """Seconds left in the host's cool-down (0 if none)."""
    try:
        h = json.loads((_dir() / "host_cooldown.json").read_text()).get(host) or {}
    except (OSError, ValueError, AttributeError):
        return 0.0
    return max(0.0, float(h.get("not_before", 0) or 0) - _now())


def host_status() -> dict:
    try:
        return json.loads((_dir() / "host_cooldown.json").read_text())
    except (OSError, ValueError):
        return {}


def record_deferral(host: str, status, retry_after_raw: Optional[str], lane: str = "") -> dict:
    """Register a 429/5xx for host; returns {'wait', 'not_before', 'consec', 'retry_after'}."""
    now = _now()
    ra = parse_retry_after(retry_after_raw, now)
    with _locked_json("host_cooldown") as d:
        h = d.get(host) or {}
        n = int(h.get("consec", 0) or 0) + 1
        wait = ra if ra is not None else min(COOL_MAX, COOL_BASE * 2 ** (n - 1))
        nb = max(float(h.get("not_before", 0) or 0), now + wait)
        h.update(consec=n, not_before=nb, last_status=status, last_retry_after=retry_after_raw, last_lane=lane,
                 last_t=now, deferrals=int(h.get("deferrals", 0) or 0) + 1, pid=os.getpid())
        d[host] = h
    return {"wait": wait, "not_before": nb, "consec": n, "retry_after": ra}


def record_success(host: str) -> None:
    try:
        if not (_dir() / "host_cooldown.json").exists():
            return
        with _locked_json("host_cooldown") as d:
            h = d.get(host)
            if h and (h.get("consec") or float(h.get("not_before", 0) or 0) > _now()):
                h.update(consec=0, not_before=0.0, last_ok=_now())
    except OSError:
        pass


# -- per-lane spacing ---------------------------------------------------------------------------------
def _lane_key(lane: str, family: str) -> str:
    return "lane." + re.sub(r"[^A-Za-z0-9_.-]", "_", f"{lane}.{family}")[:100]


def lane_wait(lane: str, family: str, interval: Optional[float] = None, stamp: bool = False) -> float:
    """Sleep until >= interval s since this lane's last request start for family; optionally stamp now.
    Returns the seconds slept. Cross-process via flock on RATE_DIR/lane.<lane>.<family>.lock."""
    if family not in LANE_SPACED_FAMILIES:
        return 0.0
    iv = LANE_MIN_INTERVAL if interval is None else interval
    slept = 0.0
    with _locked_json(_lane_key(lane, family)) as d:
        left = float(d.get("last_start", 0) or 0) + iv - _now()
        if left > 0:
            _sleep(left)
            slept = left
        if stamp:
            d["last_start"] = _now()
            d["pid"] = os.getpid()
    return slept
