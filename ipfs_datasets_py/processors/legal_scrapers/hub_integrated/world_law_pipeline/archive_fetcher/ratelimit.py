"""Box-wide (all bots, all processes) rate limiter for web-archive hosts, with per-lane fair sharing.

Files in /workspace/world_law/pipeline/archive/_ratelimit/ (dir 0777, files 0666), one set per family:
  <fam>.lock        flock(LOCK_EX) held for the whole request  -> exactly one request in flight per family
  <fam>.state.json  last_start / last_end / backoff_until / fails / last_fail_status / lane / pid / updated
  <fam>.queue.json  waiting tickets {id: {lane, pid, since, hb}} + served {lane: last time served}
  <fam>.qlock       short flock serialising writes to <fam>.queue.json (reads are lock-free, atomic rename)
  <fam>.log         audit, one line per request: start end pid outcome status lane tag (rotated at 5 MB)

  family     in flight  min spacing (end of previous -> start of next)  timeout (connect, read)  used for
  wayback    1          2.0 s                                           (10, 20) s               web.archive.org (CDX + id_)
  cc_index   1          1.0 s                                           (10, 30) s               index.commoncrawl.org
  cc_data    1          0.2 s                                           (10, 30) s               data.commoncrawl.org WARC ranges

Backoff is strictly per family: a 429/5xx/timeout on cc_index only pauses cc_index.
Fairness: waiters register a ticket with their lane; the slot goes to the waiting lane that was served least
recently (never-served lanes first), FIFO within a lane. Lane = slot(lane=...) > $ARCHIVE_LANE > $BOT_NAME/$AGENT_NAME
> "user:<login>" > "pid:<pid>".
Robustness: flock is released by the kernel when a holder dies; tickets of dead pids or with no heartbeat for
WAITER_STALE seconds are dropped; stale state (STALE_SECS) resets backoff; backoff is clamped to MAX_BACKOFF;
corrupt files are reset. Processes still running an older version of this module take <fam>.lock without a
ticket: mutual exclusion and spacing still hold, only fairness does not apply to them.
Settings are fixed in code on purpose: every importer gets the same limits.

Wayback circuit breaker (v4, box-wide, all lanes): wayback.breaker.json, read-modify-write under wayback.qlock,
atomic rename. BREAKER_THRESHOLD (3) consecutive Wayback failures across all lanes/processes (TLS/SSL errors,
connection resets, other network errors, timeouts, 429, 5xx) open it. While open, slot("wayback") raises
WaybackDown (a SlotBusy subclass, so old callers handle it) at once: callers use Common Crawl only and must
defer (not fail) items that need Wayback. One process box-wide claims a probe at most every BREAKER_PROBE_EVERY
(30 min); success closes the breaker with Wayback spacing doubled (2 s -> 4 s), stepping back by 1 s per
BREAKER_HEAL_SECS (1 h) of clean operation down to the base 2 s. wayback_available() / breaker_status() /
breaker_reset() are helpers; status() includes the breaker under "wayback_breaker".
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
import getpass
import json
import logging
import os
import random
import threading
import urllib.error
import urllib.request
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("world_law.archive.ratelimit")

RATE_DIR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/archive/_ratelimit"))
FAMILIES = {"wayback": 2.0, "cc_index": 1.0, "cc_data": 0.2}            # min spacing seconds
TIMEOUTS = {"wayback": (10, 20), "cc_index": (10, 30), "cc_data": (10, 30)}  # (connect, read) seconds
MAX_BACKOFF = 180.0       # hard cap for any shared pause (also clamps state written by older module versions)
BASE_BACKOFF = 10.0       # HARD failures (429 / 5xx / cc_data 403): 10 s, doubling, capped at MAX_BACKOFF
SOFT_BASE = 5.0           # SOFT failures (timeouts / network errors): 5 s, x1.5, capped at SOFT_MAX
SOFT_GROWTH = 1.5
SOFT_MAX = 60.0
JITTER = 0.15             # +-15 % on every pause and probe interval
PROBE_MIN = 15.0          # during a soft-only backoff with > this much left, the slot holder probes ...
PROBE_EVERY = 30.0        # ... at most every ~30 s (jittered); a good probe clears the backoff early
PROBE_URL = {"wayback": "https://web.archive.org/cdx/search/cdx?url=archive.org&limit=1&output=json",
             "cc_index": "https://index.commoncrawl.org/collinfo.json"}
PROBE_TIMEOUT = 10.0
STALE_SECS = 6 * 3600     # state not touched for this long -> ignore backoff/fails
WAIT_WARN = 300.0         # log if we waited this long for the slot
AUDIT_MAX = 5 * 1024 * 1024
POLL = 0.1                # waiter poll interval
HEARTBEAT = 3.0           # waiter refreshes its ticket this often
WAITER_STALE = 15.0       # ticket without heartbeat for this long is dropped (dead pid: dropped at once)
SERVED_TTL = 7 * 86400    # forget lanes not served for a week


class SlotBusy(Exception):
    """slot(..., max_wait=N) could not start a request within N seconds (backoff or queue)."""


class WaybackDown(SlotBusy):
    """The box-wide Wayback circuit breaker is open: skip Wayback, use Common Crawl, defer Wayback-only items."""


BREAKER_THRESHOLD = 3          # consecutive Wayback failures (all lanes) that open the breaker
BREAKER_PROBE_EVERY = 1800.0   # at most one probe per 30 min, box-wide
BREAKER_PROBE_CLAIM = 120.0    # a claimed probe whose prober died is re-claimable after this
BREAKER_SLOW_SPACING = 4.0     # Wayback spacing right after the breaker closes (half rate)
BREAKER_HEAL_SECS = 3600.0     # clean stretch per 1 s step back toward FAMILIES["wayback"]


_tls = threading.local()


def current_lane(lane: Optional[str] = None) -> str:
    if lane:
        return str(lane)[:64]
    for k in ("ARCHIVE_LANE", "BOT_NAME", "AGENT_NAME"):
        v = os.environ.get(k, "").strip()
        if v:
            return v[:64]
    try:
        u = getpass.getuser()
        if u:
            return f"user:{u}"[:64]
    except Exception:
        pass
    return f"pid:{os.getpid()}"


# -- files ----------------------------------------------------------------------------------------
def _ensure_dir() -> None:
    if not RATE_DIR.exists():
        with contextlib.suppress(FileExistsError):
            RATE_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(PermissionError):
        os.chmod(RATE_DIR, 0o777)


def _open_rw(path: Path):
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o666)
    with contextlib.suppress(PermissionError):
        os.fchmod(fd, 0o666)
    return fd


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text() or "{}")
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write_json(p: Path, d: dict) -> None:
    tmp = RATE_DIR / f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    fd = _open_rw(tmp)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(d).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, p)
    with contextlib.suppress(PermissionError):
        os.chmod(p, 0o666)


def _read_state(fam: str) -> dict:
    st = _read_json(RATE_DIR / f"{fam}.state.json")
    now = time.time()
    if now - float(st.get("updated", 0) or 0) > STALE_SECS:
        st["backoff_until"] = 0.0
        st["fails"] = 0
    if float(st.get("backoff_until", 0) or 0) > now + MAX_BACKOFF:   # bogus / clock jump
        st["backoff_until"] = now + MAX_BACKOFF
    return st


def _write_state(fam: str, st: dict) -> None:
    st["updated"] = time.time()
    st["pid"] = os.getpid()
    _write_json(RATE_DIR / f"{fam}.state.json", st)


def backoff_remaining(fam: str) -> float:
    """Seconds until the shared backoff of `fam` ends (0 if none)."""
    return max(0.0, float(_read_state(fam).get("backoff_until", 0) or 0) - time.time())


# -- ticket queue -----------------------------------------------------------------------------------
def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (ValueError, TypeError, OSError):
        return False


@contextlib.contextmanager
def _qlocked(fam: str):
    fd = _open_rw(RATE_DIR / f"{fam}.qlock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)          # held only for a read-modify-write of a small file
        p = RATE_DIR / f"{fam}.queue.json"
        q = _read_json(p)
        q.setdefault("waiters", {})
        q.setdefault("served", {})
        if not isinstance(q["waiters"], dict) or not isinstance(q["served"], dict):
            q = {"waiters": {}, "served": {}}
        yield q
        _write_json(p, q)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _stale(w: dict, now: float) -> bool:
    return now - float(w.get("hb", 0) or 0) > WAITER_STALE or not _pid_alive(w.get("pid"))


def _prune(q: dict, now: float) -> None:
    for k in [k for k, w in q["waiters"].items() if _stale(w, now)]:
        del q["waiters"][k]
    for lane in [l for l, t in q["served"].items() if now - float(t or 0) > SERVED_TTL]:
        del q["served"][lane]


def _winner(q: dict, now: float) -> Optional[str]:
    """Ticket id to serve next: lane served least recently among live waiters, FIFO within the lane."""
    best = None
    for k, w in q.get("waiters", {}).items():
        if _stale(w, now):
            continue
        key = (float(q.get("served", {}).get(w.get("lane"), 0) or 0), float(w.get("since", 0) or 0), k)
        if best is None or key < best:
            best = key
    return best[2] if best else None


# -- Wayback circuit breaker ---------------------------------------------------------------------------
_BRK = "wayback.breaker.json"


@contextlib.contextmanager
def _brk_locked():
    """Read-modify-write of the breaker under wayback.qlock (short flock), atomic write on exit."""
    _ensure_dir()
    fd = _open_rw(RATE_DIR / "wayback.qlock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        b = _read_json(RATE_DIR / _BRK)
        before = json.dumps(b, sort_keys=True)
        b.setdefault("state", "closed")
        yield b
        if json.dumps(b, sort_keys=True) != before:
            b["updated"] = time.time()
            _write_json(RATE_DIR / _BRK, b)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _brk_read() -> dict:
    b = _read_json(RATE_DIR / _BRK)
    b.setdefault("state", "closed")
    return b


def breaker_status() -> dict:
    b = _brk_read()
    now = time.time()
    b["spacing_now"] = _spacing("wayback", b)
    if b.get("state") == "open":
        b["next_probe_in"] = round(max(0.0, float(b.get("last_probe", 0) or 0) + BREAKER_PROBE_EVERY - now), 1)
        b["open_for"] = round(now - float(b.get("opened_at", now) or now), 1)
    return b


def wayback_available() -> bool:
    """False while the box-wide breaker is open (callers: skip Wayback, defer Wayback-only items).
    Returns True when a probe is due, so the next slot('wayback') can claim it (losers get WaybackDown)."""
    b = _brk_read()
    if b.get("state") != "open":
        return True
    now = time.time()
    claim = b.get("probe_claim") or {}
    claim_live = bool(claim) and now - float(claim.get("t", 0) or 0) < BREAKER_PROBE_CLAIM and _pid_alive(claim.get("pid"))
    return now - float(b.get("last_probe", 0) or 0) >= BREAKER_PROBE_EVERY and not claim_live


def breaker_reset() -> None:
    """Manual close (operator use). Keeps the slowed spacing."""
    with _brk_locked() as b:
        if b.get("state") == "open":
            b.update(state="closed", closed_at=time.time(), spacing=BREAKER_SLOW_SPACING,
                     healthy_since=time.time(), consec_fails=0, closed_by="manual")


def _spacing(fam: str, b: Optional[dict] = None) -> float:
    base = FAMILIES[fam]
    if fam != "wayback":
        return base
    b = _brk_read() if b is None else b
    sp = float(b.get("spacing", base) or base)
    if sp <= base:
        return base
    healthy = time.time() - float(b.get("healthy_since", time.time()) or time.time())
    return max(base, sp - int(max(0.0, healthy) // BREAKER_HEAL_SECS) * 1.0)


def _brk_is_fail(status) -> bool:
    return status is None or isinstance(status, str) or (isinstance(status, int) and (status == 429 or status >= 500))


def _brk_record(ok: bool, status=None, lane: str = "") -> None:
    try:
        with _brk_locked() as b:
            now = time.time()
            if ok:
                if int(b.get("consec_fails", 0) or 0):
                    b["consec_fails"] = 0
                if b.get("state") != "open":
                    sp = float(b.get("spacing", FAMILIES["wayback"]) or 0)
                    if sp > FAMILIES["wayback"] and _spacing("wayback", b) <= FAMILIES["wayback"]:
                        b["spacing"] = FAMILIES["wayback"]          # fully healed
                return
            b["healthy_since"] = now
            if b.get("state") == "open":
                return
            n = int(b.get("consec_fails", 0) or 0) + 1
            b["consec_fails"] = n
            b["last_fail"] = {"t": now, "status": status, "lane": lane, "pid": os.getpid()}
            if n >= BREAKER_THRESHOLD:
                b.update(state="open", opened_at=now, last_probe=now, prober_pid=None,
                         reason=f"{n} consecutive failures, last {status} ({lane})",
                         opens=int(b.get("opens", 0) or 0) + 1)
                log.warning("WAYBACK BREAKER OPEN: %s; Common Crawl only, next probe in %.0f min",
                            b["reason"], BREAKER_PROBE_EVERY / 60)
    except OSError as e:  # never let breaker bookkeeping break a request
        log.debug("breaker update failed: %s", e)


def _brk_gate(lane: str) -> None:
    """Called at slot('wayback') entry. Raises WaybackDown while open unless this process wins the probe claim
    and the probe succeeds (then the breaker closes and the caller proceeds normally)."""
    b = _brk_read()
    if b.get("state") != "open":
        return
    now = time.time()
    claimed = False
    with _brk_locked() as b:
        if b.get("state") != "open":
            return
        lp = float(b.get("last_probe", 0) or 0)
        claim = b.get("probe_claim") or {}
        claim_live = claim and now - float(claim.get("t", 0) or 0) < BREAKER_PROBE_CLAIM and _pid_alive(claim.get("pid"))
        if now - lp >= BREAKER_PROBE_EVERY and not claim_live:
            b["probe_claim"] = {"pid": os.getpid(), "t": now, "lane": lane}
            claimed = True
    if not claimed:
        raise WaybackDown(f"wayback breaker open ({b.get('reason')}); next probe in "
                          f"{max(0.0, float(b.get('last_probe', 0) or 0) + BREAKER_PROBE_EVERY - now) / 60:.0f} min")
    good, code = False, None
    fd = _open_rw(RATE_DIR / "wayback.lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)                # one request in flight still holds for the probe
        held = getattr(_tls, "held", None)
        if held is None:
            held = _tls.held = set()
        held.add("wayback")
        try:
            t0 = time.time()
            good, code = _probe("wayback")
        finally:
            held.discard("wayback")
        preq = Request("wayback", {}, lane)
        preq.started, preq.tag = t0, "BREAKER_PROBE " + PROBE_URL["wayback"]
        preq.outcome, preq.status = ("ok" if good else "probe_fail"), code
        _audit("wayback", preq, time.time())
        st = _read_state("wayback")
        st["last_end"] = time.time()
        if good:
            _clear(st)
        _write_state("wayback", st)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    with _brk_locked() as b:
        b.pop("probe_claim", None)
        b["last_probe"] = time.time()
        b["last_probe_result"] = code
        b["probes"] = int(b.get("probes", 0) or 0) + 1
        if good and b.get("state") == "open":
            b.update(state="closed", closed_at=time.time(), consec_fails=0, spacing=BREAKER_SLOW_SPACING,
                     healthy_since=time.time(), closed_by=f"probe pid {os.getpid()} ({lane})")
            log.warning("WAYBACK BREAKER CLOSED by probe (%s); spacing %.0fs", code, BREAKER_SLOW_SPACING)
    if not good:
        raise WaybackDown(f"wayback breaker open; probe failed ({code}), next in {BREAKER_PROBE_EVERY / 60:.0f} min")


# -- request handle ----------------------------------------------------------------------------------
class Request:
    """Handle yielded by `slot()`; call .ok(status) / .fail(status) to update the family's backoff."""

    def __init__(self, fam: str, st: dict, lane: str, nested: bool = False):
        self.fam, self.st, self.lane, self.started = fam, st, lane, time.time()
        self.outcome = None
        self.status = None
        self.tag = None
        self.nested = nested
        self.timeout = TIMEOUTS[fam]

    def ok(self, status=None) -> None:
        self.outcome = "ok"
        self.status = status
        if self.fam == "wayback" and not self.nested and not getattr(self, "_brk_done", False):
            self._brk_done = True
            _brk_record(True, status, self.lane)

    def fail(self, status=None, retry_after: float | None = None) -> float:
        """Register a failure for THIS family only and return the pause length.
        HARD (int 429, int >= 500, or a 403 from cc_data, or any Retry-After): 10 s doubling, cap 180 s.
        SOFT (timeouts / network errors / status None or a string): 5 s x1.5, cap 60 s, and the slot holder
        probes the host during the pause and clears it early when the probe succeeds."""
        if self.nested:
            return 0.0
        status = status if status is not None else "timeout_or_neterr"
        pause = _register_fail(self.fam, self.st, status, retry_after)
        if self.fam == "wayback" and _brk_is_fail(status) and not getattr(self, "_brk_done", False):
            self._brk_done = True
            _brk_record(False, status, self.lane)
        self.outcome = "fail"
        self.status = status
        return pause


def _is_hard(fam, status, retry_after) -> bool:
    if retry_after:
        return True
    return isinstance(status, int) and (status == 429 or status >= 500 or (status == 403 and fam == "cc_data"))


def _jit(x: float) -> float:
    return x * random.uniform(1 - JITTER, 1 + JITTER)


def _register_fail(fam, st, status, retry_after=None) -> float:
    if not int(st.get("fails", 0) or 0):          # an older module copy reset only `fails` on success
        st["hard_fails"] = st["soft_fails"] = 0
        st["hard"] = False
    if _is_hard(fam, status, retry_after):
        hf = int(st.get("hard_fails", 0) or 0) + 1
        st["hard_fails"] = hf
        st["hard"] = True
        pause = retry_after if retry_after else BASE_BACKOFF * (2 ** (hf - 1))
        pause = min(MAX_BACKOFF, _jit(pause))
    else:
        sf = int(st.get("soft_fails", 0) or 0) + 1
        st["soft_fails"] = sf
        pause = min(SOFT_MAX, _jit(SOFT_BASE * (SOFT_GROWTH ** (sf - 1))))
    st["fails"] = int(st.get("hard_fails", 0) or 0) + int(st.get("soft_fails", 0) or 0)
    st["backoff_until"] = max(float(st.get("backoff_until", 0) or 0), time.time() + pause)
    st["last_fail_status"] = status
    st["last_fail_kind"] = "hard" if _is_hard(fam, status, retry_after) else "soft"
    return pause


def _clear(st) -> None:
    for k in ("fails", "hard_fails", "soft_fails"):
        st[k] = 0
    st["hard"] = False
    st["backoff_until"] = 0.0


def _probe(fam: str) -> tuple:
    """One small health request (caller holds the slot). Returns (ok, status)."""
    url = PROBE_URL.get(fam)
    if not url:
        return False, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WorldLaw-ArchiveFetcher/1.0 (box-wide limiter health probe; JusticeDAO world_law)"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            r.read(4096)
            return 200 <= r.status < 300, r.status
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception as e:  # timeout / network
        return False, type(e).__name__


def _audit(fam: str, req: Request, end: float) -> None:
    p = RATE_DIR / f"{fam}.log"
    try:
        if p.exists() and p.stat().st_size > AUDIT_MAX:
            os.replace(p, RATE_DIR / f"{fam}.log.1")
        fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            with contextlib.suppress(PermissionError):
                os.fchmod(fd, 0o666)
            line = "%.3f\t%.3f\t%d\t%s\t%s\t%s\t%s\n" % (
                req.started, end, os.getpid(), req.outcome or "?", req.status or "",
                req.lane.replace("\t", " "), (req.tag or "").replace("\t", " ").replace("\n", " "))
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except OSError:
        pass


# -- the slot ------------------------------------------------------------------------------------------
@contextlib.contextmanager
def slot(fam: str, lane: Optional[str] = None, max_wait: Optional[float] = None):
    """Wait for the box-wide slot of `fam` (fair across lanes), honour spacing + the family's backoff,
    yield a Request. One request in flight per family; last_end recorded on exit.

    max_wait: raise SlotBusy instead of waiting longer than this many seconds (incl. backoff). Use it for
    optional sources (e.g. Common Crawl before a Wayback fallback) so one family's outage never stalls a
    worker that has other work. Re-entrant per thread (a nested slot of the same family is a no-op).
    """
    if fam not in FAMILIES:
        raise ValueError(f"unknown family {fam}")
    lane = current_lane(lane)
    held = getattr(_tls, "held", None)
    if held is None:
        held = _tls.held = set()
    if fam in held:                                   # e.g. sitecustomize hook under ArchiveFetcher
        yield Request(fam, {}, lane, nested=True)
        return
    _ensure_dir()
    if fam == "wayback":
        _brk_gate(lane)                               # raises WaybackDown while the breaker is open
    t0 = time.time()
    deadline = t0 + max_wait if max_wait is not None else None
    if deadline is not None and backoff_remaining(fam) > max_wait:
        raise SlotBusy(f"{fam} backing off for {backoff_remaining(fam):.0f}s")

    wid = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"
    me = {"lane": lane, "pid": os.getpid(), "since": t0, "hb": t0}
    with _qlocked(fam) as q:
        _prune(q, t0)
        q["waiters"][wid] = me
    qpath = RATE_DIR / f"{fam}.queue.json"
    fd = _open_rw(RATE_DIR / f"{fam}.lock")
    locked = False
    warned = False
    try:
        last_hb = t0
        while True:
            now = time.time()
            q = _read_json(qpath)
            waiters = q.get("waiters", {}) if isinstance(q.get("waiters"), dict) else {}
            if wid not in waiters or now - last_hb > HEARTBEAT or any(_stale(w, now) for w in waiters.values()):
                with _qlocked(fam) as q:
                    _prune(q, now)
                    me["hb"] = now
                    q["waiters"][wid] = me
                last_hb = now
            if _winner(q, now) == wid or wid not in waiters:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                if locked:
                    # re-check under the queue lock that nobody with priority registered meanwhile
                    with _qlocked(fam) as q:
                        _prune(q, now)
                        q["waiters"][wid] = me
                        if _winner(q, now) == wid:
                            del q["waiters"][wid]
                            q["served"][lane] = time.time()
                            break
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    locked = False
            if deadline is not None and now > deadline:
                raise SlotBusy(f"{fam}: no slot within {max_wait:.0f}s")
            if fam == "wayback" and _brk_read().get("state") == "open":
                raise WaybackDown("wayback breaker opened while waiting")
            if not warned and now - t0 > WAIT_WARN:
                log.warning("lane %s waited %.0fs for the box-wide %s slot", lane, now - t0, fam)
                warned = True
            time.sleep(POLL)

        while True:
            st = _read_state(fam)
            now = time.time()
            # last_start > last_end means the previous holder died mid-request: space from its start instead
            prev = max(float(st.get("last_end", 0) or 0), float(st.get("last_start", 0) or 0))
            bo = float(st.get("backoff_until", 0) or 0)
            start = max(now, prev + _spacing(fam), bo)
            if fam == "wayback" and _brk_read().get("state") == "open":
                raise WaybackDown("wayback breaker opened while waiting")
            if start <= now:
                break
            if deadline is not None and start > deadline:
                raise SlotBusy(f"{fam} backing off for {start - now:.0f}s")
            if (bo - now > PROBE_MIN and not st.get("hard") and not _is_hard(fam, st.get("last_fail_status"), None) and fam in PROBE_URL and now >= prev + _spacing(fam)
                    and now - float(st.get("last_probe", 0) or 0) > _jit(PROBE_EVERY)):
                preq = Request(fam, st, lane)
                preq.tag = "PROBE " + PROBE_URL[fam]
                held.add(fam)                 # so a patched urllib (rlhook) treats the probe as nested
                try:
                    good, code = _probe(fam)
                finally:
                    held.discard(fam)
                st["last_probe"] = time.time()
                if good:
                    _clear(st)
                    preq.ok(code)
                    log.info("%s probe ok -> soft backoff cleared early", fam)
                else:
                    preq.outcome, preq.status = "probe_fail", code
                st["last_end"] = time.time()
                _write_state(fam, st)
                _audit(fam, preq, st["last_end"])
                continue
            time.sleep(min(start - now, 5.0))
        st["last_start"] = time.time()
        st["lane"] = lane
        _write_state(fam, st)
        req = Request(fam, st, lane)
        held.add(fam)
        try:
            yield req
        finally:
            held.discard(fam)
            if req.outcome == "ok":
                _clear(st)
            st["last_end"] = time.time()
            _write_state(fam, st)
            _audit(fam, req, st["last_end"])
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        if not locked:
            with contextlib.suppress(Exception):
                with _qlocked(fam) as q:
                    q["waiters"].pop(wid, None)


def status() -> dict:
    _ensure_dir()
    out = {}
    now = time.time()
    for f in FAMILIES:
        st = _read_state(f)
        q = _read_json(RATE_DIR / f"{f}.queue.json")
        st["waiting"] = sorted({w.get("lane") for w in (q.get("waiters") or {}).values() if not _stale(w, now)})
        st["backoff_remaining"] = round(max(0.0, float(st.get("backoff_until", 0) or 0) - now), 1)
        out[f] = st
    out["wayback_breaker"] = breaker_status()
    return out
