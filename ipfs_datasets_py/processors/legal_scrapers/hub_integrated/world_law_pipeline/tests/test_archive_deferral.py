"""Shared ArchiveFetcher 429/5xx deferral: no in-process retry, per-host cool-down (Retry-After seconds / HTTP-date,
default 60 s doubling capped at 900 s, reset on success), >= 5 s per-lane spacing, deferrals never trip the box-wide
Wayback breaker. Mocked HTTP, temp RATE_DIR (never touches the live limiter state).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_archive_deferral.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import email.utils
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from archive import ratelimit as rl, deferral as dfr  # noqa: E402
from archive.core import ArchiveFetcher, ArchiveDeferred, ArchiveTransient  # noqa: E402

rl.FAMILIES["wayback"] = 0.0          # no shared 2 s spacing in tests (lane spacing is tested via a fake clock)
rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="deftest_rl_"))


class Clock:
    def __init__(self):
        self.t = time.time()
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Raw:
    def __init__(self, b): self.b = b
    def read(self, n=-1, decode_content=False): return self.b


class Resp:
    def __init__(self, status, headers=None, body=b"x" * 300):
        self.status_code, self.headers, self.body = status, headers or {}, body
        self.raw = Raw(body)
        self.url = "https://web.archive.org/"
    def iter_content(self, n): yield self.body
    def close(self): pass


def fresh(responses, interval=0.0):
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="deftest_rl_"))
    dfr.LANE_MIN_INTERVAL = interval
    fx = ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="deftest_c_"), use_cc=False, lane="testlane")
    calls = []

    def get(url, **kw):
        calls.append(url)
        return responses.pop(0)
    fx.s.get = get
    return fx, calls


URL = "https://web.archive.org/web/2020id_/https://x.org/a"


def test_no_immediate_retry_and_ra_seconds():
    fx, calls = fresh([Resp(429, {"Retry-After": "120"}), Resp(200)])
    t0 = time.time()
    try:
        fx._get("wayback", URL); assert False, "expected deferral"
    except ArchiveDeferred as e:
        assert isinstance(e, ArchiveTransient)                  # backward compatible
        assert e.status == 429 and e.host == "web.archive.org" and abs(e.retry_after - 120) < 1
        assert 118 < e.retry_in <= 120.5
    assert len(calls) == 1, f"retried in-process: {calls}"
    assert time.time() - t0 < 5, "slept instead of deferring"
    # host is cooling down: next call defers WITHOUT sending a request
    try:
        fx._get("wayback", URL); assert False
    except ArchiveDeferred as e:
        assert e.status is None and e.retry_in > 100
    assert len(calls) == 1 and fx.stats.get("wayback_deferred_cooldown") == 1
    print("ok no immediate retry + Retry-After seconds")


def test_ra_http_date():
    when = time.time() + 300
    hd = email.utils.formatdate(when, usegmt=True)
    assert abs(dfr.parse_retry_after(hd) - 300) < 2
    assert dfr.parse_retry_after("garbage") is None and dfr.parse_retry_after(None) is None
    assert dfr.parse_retry_after(email.utils.formatdate(time.time() - 50, usegmt=True)) == 0.0
    fx, calls = fresh([Resp(503, {"Retry-After": hd})])
    try:
        fx._get("wayback", URL); assert False
    except ArchiveDeferred as e:
        assert e.status == 503 and 295 < e.retry_in <= 301, e.retry_in
    print("ok Retry-After HTTP-date")


def test_default_doubling_cap_reset():
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="deftest_rl_"))
    waits = [dfr.record_deferral("h.example", 429, None)["wait"] for _ in range(7)]
    assert waits == [60, 120, 240, 480, 900, 900, 900], waits
    dfr.record_success("h.example")
    assert dfr.host_cooldown("h.example") == 0
    assert dfr.record_deferral("h.example", 500, None)["wait"] == 60
    # end-to-end: success through the fetcher resets the host
    fx, calls = fresh([Resp(500), Resp(200)])
    try: fx._get("wayback", URL)
    except ArchiveDeferred as e: assert 55 < e.retry_in <= 60.5
    with dfr._locked_json("host_cooldown") as d: d["web.archive.org"]["not_before"] = 0   # pretend it expired
    assert fx._get("wayback", URL).status_code == 200
    assert dfr.host_status()["web.archive.org"]["consec"] == 0
    print("ok default 60 s doubling, 900 s cap, reset on success")


def test_lane_spacing():
    clk = Clock()
    dfr._now, dfr._sleep = clk.now, clk.sleep
    try:
        fx, calls = fresh([Resp(200), Resp(200), Resp(200)], interval=5.0)
        stamps = []
        orig = fx.s.get
        fx.s.get = lambda url, **kw: (stamps.append(clk.t), orig(url, **kw))[1]
        for _ in range(3):
            fx._get("wayback", URL)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        assert all(g >= 5.0 - 1e-6 for g in gaps), gaps
        # other lane is independent; cc_* families are not lane-spaced by default
        assert dfr.lane_wait("otherlane", "wayback") == 0.0
        assert dfr.lane_wait("testlane", "cc_data") == 0.0
    finally:
        dfr._now, dfr._sleep = time.time, time.sleep
    print("ok >= 5 s per-lane spacing", [round(g, 2) for g in gaps])


def test_breaker_not_tripped():
    fx, calls = fresh([Resp(429), Resp(503), Resp(502), Resp(429), Resp(500)])
    for i in range(5):
        with dfr._locked_json("host_cooldown") as d: d.pop("web.archive.org", None)   # let each one through
        try: fx._get("wayback", URL); assert False
        except ArchiveDeferred: pass
    b = rl.breaker_status()
    assert b.get("state") != "open" and not int(b.get("consec_fails", 0) or 0), b
    assert rl.wayback_available() and len(calls) == 5
    # legacy mode (defer_on_throttle=False) still retries + counts toward the breaker, as before
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="deftest_rl_"))
    old = ArchiveFetcher(cache_dir=tempfile.mkdtemp(), use_cc=False, lane="t", max_retries=1, defer_on_throttle=False)
    old.s.get = lambda url, **kw: Resp(429)
    try: old._get("wayback", URL); assert False
    except ArchiveDeferred: assert False, "legacy mode must not defer"
    except ArchiveTransient: pass
    assert int(rl.breaker_status().get("consec_fails", 0)) == 1
    print("ok deferrals never trip the breaker (legacy mode still counts)")


if __name__ == "__main__":
    test_no_immediate_retry_and_ra_seconds()
    test_ra_http_date()
    test_default_doubling_cap_reset()
    test_lane_spacing()
    test_breaker_not_tripped()
    print("ALL OK test_archive_deferral")
