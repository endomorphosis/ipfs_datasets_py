"""National review round 3 (2026-10-18): per-call timeout skip + breaker budget, retryable vs permanent truncation,
typed exceptions (no message parsing), strict *_ex kwargs. Mocked HTTP, temp RATE_DIR, no network.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_archive_deferral4.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from archive import ratelimit as rl, deferral as dfr  # noqa: E402
from archive.core import (ArchiveFetcher, ArchiveDeferred, ArchiveTransient, ArchiveError, ArchiveTimeout,  # noqa: E402
                          ArchiveBreakerOpen, ArchiveBusy, Capture)

rl.FAMILIES.update(wayback=0.0, cc_index=0.0, cc_data=0.0)
dfr.LANE_MIN_INTERVAL = 0.0
rl.SOFT_BASE = rl.SOFT_MAX = rl.BASE_BACKOFF = 0.01   # no real pauses in tests


def fx(**kw):
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="def4_rl_"))
    return ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="def4_c_"), lane="t", **kw)


WB4 = [Capture("wayback", "wayback", f"2024010{i}000000", "https://x.org/a", 200) for i in range(1, 5)]
CC4 = [Capture("commoncrawl", "CC-MAIN-2026-39", f"2025010{i}000000", "https://x.org/a", 200, None, None, 100,
               f"f{i}.warc.gz", 1) for i in range(1, 5)]


def consec():
    return int(rl.breaker_status().get("consec_fails", 0) or 0)


def test_timeout_skip_and_breaker_budget():
    f = fx()
    n = []
    f.s.get = lambda url, **kw: (n.append(url), (_ for _ in ()).throw(requests.Timeout("read timed out")))[1]
    try:
        f.fetch_best(WB4); assert False
    except ArchiveDeferred as e:
        info = e.fetch_info
        assert e.reason == "timeout" and info.skip_sources == {"wayback": "timeout"} and info.skipped == {"wayback": 3}
        assert info.wb_deferred == 4
    assert len(n) == 2, n                     # 1 capture x (try + single retry); the other 3 never requested
    assert consec() == 1 and rl.wayback_available(), consec()   # one call -> at most ONE breaker failure
    # a second and third item each add one more: the breaker needs 3 separate items
    for _ in range(2):
        try:
            f.fetch_best(WB4)
        except ArchiveDeferred:
            pass
    assert consec() == 3 and not rl.wayback_available()
    # skipped captures don't use max_tries: CC timeout then Wayback still tried (max_tries=2)
    g = fx()
    calls = []

    def fc(cap):
        calls.append(cap.source)
        if cap.source == "commoncrawl":
            raise ArchiveTimeout("cc_data giving up after 2 timeout/network failure(s)")
        raise ArchiveError("wayback replay http 404", status=404)
    g.fetch_capture = fc
    try:
        g.fetch_best(CC4 + WB4[:2], max_tries=2); assert False
    except ArchiveDeferred as e:
        assert calls == ["commoncrawl", "wayback"] and e.fetch_info.skipped == {"commoncrawl": 3}
    # fetch_newest: the source skip carries into the second (CC + Wayback) pass
    h = fx()
    calls.clear()
    h.fetch_capture = fc
    h.cc_crawls = lambda: ["A"]
    h._cc_query = lambda *a, **k: list(CC4)
    h.wb_captures = lambda *a, **k: list(WB4[:1])
    d, info = h.fetch_newest_ex("https://x.org/a")
    assert d is None and calls.count("commoncrawl") == 1 and info.skip_sources.get("commoncrawl") == "timeout"
    print("ok 3 timeout skips the rest of the source (no request, no max_tries); <=1 breaker failure per call")


def test_listing_timeout_counts_once():
    f = fx()
    f.cc_crawls = lambda: ["A", "B", "C", "D"]
    seen = []

    def q(crawl, *a, **k):
        seen.append(crawl)
        raise ArchiveTimeout(f"cc_index giving up on {crawl} after 2 timeout/network failure(s)")
    f._cc_query = q
    r = f.cc_captures("x.org/")
    assert seen == ["A", "B", "C", "D"], seen   # timeouts count once toward the CC breaker: all crawls tried
    assert r.truncated_reason == "timeout" and r.retryable_truncation and not r.complete_except_permanent
    # Wayback listing: CDX pages timing out inside one list_captures add one breaker failure
    g = fx(use_cc=False)
    g.s.get = lambda url, **kw: (_ for _ in ()).throw(requests.Timeout("t"))
    r = g.list_captures("x.org/")
    assert r.truncated_reason == "timeout" and consec() == 1
    print("ok 3b listings: CC timeouts don't trip the CC breaker; one Wayback breaker failure per call")


def test_permanent_vs_retryable():
    f = fx()
    f.cc_crawls = lambda: ["A", "B", "C"]
    f._cc_query = lambda crawl, *a, **k: ((_ for _ in ()).throw(ArchiveError("cc page 410", status=410))
                                         if crawl == "B" else [])
    r = f.cc_captures("x.org/")
    assert r.truncated and r.truncated_reason == "crawl_failed" and r.deferral is None
    assert r.complete_except_permanent and not r.retryable_truncation and any("permanent" in e for e in r.errors)
    f._cc_query = lambda crawl, *a, **k: ((_ for _ in ()).throw(ArchiveError("cc page 503", status=503))
                                         if crawl == "B" else [])
    r = f.cc_captures("x.org/")
    assert r.retryable_truncation and not r.complete_except_permanent
    # crawl list: network error -> retryable; 404 -> permanent
    f.cc_crawls = lambda: (_ for _ in ()).throw(ArchiveTimeout("cc_index giving up on collinfo"))
    r = f.cc_captures("x.org/")
    assert r.truncated_reason == "crawl_list_unavailable" and r.retryable_truncation and r.deferral.reason == "timeout"
    f.cc_crawls = lambda: (_ for _ in ()).throw(ArchiveError("cc collinfo 404", status=404))
    r = f.cc_captures("x.org/")
    assert r.truncated_reason == "crawl_list_unavailable" and r.complete_except_permanent
    # real cc_crawls path: network error -> ArchiveTimeout -> retryable
    g = fx(timeout_retries=0)
    g.s.get = lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError("down"))
    r = g.cc_captures("x.org/")
    assert r.truncated_reason == "crawl_list_unavailable" and r.retryable_truncation
    # complete listing: complete_except_permanent True, not truncated
    h = fx()
    h.cc_crawls = lambda: ["A"]
    h._cc_query = lambda *a, **k: []
    r = h.cc_captures("x.org/")
    assert not r.truncated and r.complete_except_permanent and not r.retryable_truncation
    print("ok 1 retryable_truncation / complete_except_permanent split (404/410 permanent, network/5xx retryable)")


def test_typed_exceptions():
    assert issubclass(ArchiveTimeout, ArchiveTransient) and issubclass(ArchiveBreakerOpen, ArchiveTransient)
    assert issubclass(ArchiveBusy, ArchiveTransient) and issubclass(ArchiveTransient, ArchiveError)
    f = fx()
    # the reason comes from the type, not the message
    assert f._as_deferral(ArchiveTimeout("something odd"), "wayback").reason == "timeout"
    assert f._as_deferral(ArchiveBreakerOpen("x"), "wayback").reason == "breaker_open"
    assert f._as_deferral(ArchiveBusy("x"), "cc_index").reason == "busy"
    assert f._as_deferral(ArchiveTransient("the breaker timed out (message only)"), "wayback").reason == "transient"
    assert f._as_deferral(ArchiveTransient("x", kind="timeout"), "wayback").reason == "timeout"
    # raised types from the real paths, old messages kept
    f.s.get = lambda url, **kw: (_ for _ in ()).throw(requests.Timeout("t"))
    try:
        f._get("cc_data", "https://data.commoncrawl.org/x"); assert False
    except ArchiveTimeout as e:
        assert "giving up" in str(e) and "timeout" in str(e) and e.kind == "timeout"
    rl.breaker_open = getattr(rl, "breaker_open", None)
    import archive.core as core
    orig = core.ratelimit.wayback_available
    core.ratelimit.wayback_available = lambda: False
    try:
        f.wb_captures("x.org"); assert False
    except ArchiveBreakerOpen as e:
        assert "breaker open" in str(e)
    finally:
        core.ratelimit.wayback_available = orig
    assert ArchiveDeferred("x", status=429).kind == "deferred" and ArchiveError("e", status=404).permanent
    assert not ArchiveError("e", status=503).permanent and not ArchiveTimeout("t").permanent
    print("ok 2 typed exceptions: ArchiveTimeout / ArchiveBreakerOpen / ArchiveBusy + .kind; messages kept")


def test_ex_kwargs():
    f = fx()
    for fn, arg in ((f.fetch_best_ex, []), (f.fetch_newest_ex, "https://x.org/a")):
        try:
            fn(arg, bogus=1); assert False
        except TypeError:
            pass
    f.fetch_capture = lambda c: (_ for _ in ()).throw(ArchiveTimeout("t"))
    d, info = f.fetch_best_ex(CC4)                       # default: return, never raise
    assert d is None and isinstance(info.exception, ArchiveDeferred)
    try:
        f.fetch_best_ex(CC4, raise_deferred=True); assert False
    except ArchiveDeferred as e:
        assert e.fetch_info is not None
    g = fx(raise_deferred=True)                          # the fetcher default does NOT apply to *_ex
    g.fetch_capture = f.fetch_capture
    assert g.fetch_best_ex(CC4)[0] is None
    print("ok 4 *_ex: unknown kwargs -> TypeError; raise_deferred explicit (default False)")


if __name__ == "__main__":
    test_timeout_skip_and_breaker_budget()
    test_listing_timeout_counts_once()
    test_permanent_vs_retryable()
    test_typed_exceptions()
    test_ex_kwargs()
    print("ALL OK test_archive_deferral4")
