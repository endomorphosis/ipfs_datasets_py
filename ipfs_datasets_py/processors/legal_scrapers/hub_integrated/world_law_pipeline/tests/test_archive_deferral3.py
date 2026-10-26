"""ArchiveFetcher completeness signals (2026-10-18, national review): cc_captures / list_captures flag .truncated with
a reason for EVERY early stop or failure (timeouts, crawl list unavailable, CC breaker, Wayback breaker, failed CDX);
fetch_best None strictly means "every source answered, nothing usable" (timeouts / breaker / throttle -> ArchiveDeferred);
a doc found while another source failed carries doc.incomplete / doc.deferral / doc.fetch_info; per-call context
survives nested calls (doc.fetch_info, e.fetch_info, fetch_best_ex). Mocked, temp RATE_DIR, no network.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_archive_deferral3.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from archive import ratelimit as rl, deferral as dfr  # noqa: E402
from archive.core import (ArchiveFetcher, ArchiveDeferred, ArchiveTransient, ArchiveError, ArchivedDoc, ArchiveTimeout, ArchiveBreakerOpen,  # noqa: E402
                          Capture, CaptureList, FetchInfo)

rl.FAMILIES.update(wayback=0.0, cc_index=0.0, cc_data=0.0)
dfr.LANE_MIN_INTERVAL = 0.0
TIMEOUT = ArchiveTimeout("cc_index giving up on x after 2 timeout/network failure(s) (timeout_retries=1): ReadTimeout")


def fx(**kw):
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="def3_rl_"))
    return ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="def3_c_"), lane="t", **kw)


def doc(src, body=b"law text "):
    return ArchivedDoc("https://x.org/a", src, "c", "2026-01-01T00:00:00Z", "u", 200, "text/html",
                       body=b"<html><body>" + body * 50 + b"</body></html>")


CC = [Capture("commoncrawl", "CC-MAIN-2026-39", f"2025010{i}000000", "https://x.org/a", 200, None, None, None,
              "f.warc.gz", 1) for i in range(1, 3)]
WB = [Capture("wayback", "wayback", "20240101000000", "https://x.org/a", 200)]


def test_cc_captures_truncation():
    f = fx()
    f.cc_crawls = lambda: ["A", "B", "C"]
    seen = []

    def q_timeout(crawl, *a, **k):
        seen.append(crawl)
        if crawl == "B":
            raise TIMEOUT
        return [CC[0]]
    f._cc_query = q_timeout
    got = f.cc_captures("x.org/", "prefix")
    assert got.truncated and got.truncated_reason == "timeout" and got.deferred and len(got) == 2
    assert got.deferral.reason == "timeout" and got.deferral.families == ["cc_index"] and got.deferral.retry_in >= 55
    assert seen == ["A", "B", "C"] and any("timeout" in e for e in got.errors)       # timeout: other crawls still tried
    try:
        f.cc_captures("x.org/", "prefix", on_deferred="raise"); assert False
    except ArchiveDeferred as e:
        assert e.reason == "timeout" and len(e.partial) == 2
    try:
        f.cc_captures("x.org/", "prefix", on_error="raise"); assert False
    except ArchiveDeferred as e:
        assert len(e.partial) == 1                     # stopped at the failing crawl
    # crawl list unavailable: permanent -> truncated, no deferral; transient -> truncated + deferral
    g = fx()
    g.cc_crawls = lambda: (_ for _ in ()).throw(ArchiveError("collinfo http 404", status=404))
    r = g.cc_captures("x.org/")
    assert r.truncated and r.truncated_reason == "crawl_list_unavailable" and r.deferral is None and not r.deferred
    assert g.cc_captures("x.org/", on_deferred="raise").truncated            # permanent: flagged, not raised
    try:
        g.cc_captures("x.org/", on_error="raise"); assert False
    except ArchiveError as e:
        assert not isinstance(e, ArchiveTransient)
    g.cc_crawls = lambda: (_ for _ in ()).throw(TIMEOUT)
    r = g.cc_captures("x.org/")
    assert r.truncated_reason == "crawl_list_unavailable" and r.deferral is not None and r.deferral.reason == "timeout"
    # CC breaker: 2 consecutive failed crawls stop the loop early
    h = fx()
    h.cc_crawls = lambda: ["A", "B", "C", "D"]
    seen.clear()

    def q_bad(crawl, *a, **k):
        seen.append(crawl)
        raise ArchiveError("cc page 400", status=400)
    h._cc_query = q_bad
    r = h.cc_captures("x.org/")
    assert r.truncated and r.truncated_reason == "crawl_failed" and seen == ["A", "B"]
    assert any(e.startswith("cc_breaker") for e in r.errors) and r.deferral.reason == "cc_breaker" and r.retryable_truncation
    # clean listing
    h._cc_query = lambda *a, **k: [CC[0]]
    ok = h.cc_captures("x.org/")
    assert not ok.truncated and ok.truncated_reason is None and not ok.errors and len(ok) == 4
    print("ok 1 cc_captures: truncated + reason for timeout / crawl list / CC breaker; raise modes consistent")


def test_list_captures_wayback_failures():
    f = fx(use_cc=False)
    for exc, reason, deferred in ((ArchiveBreakerOpen("wayback breaker open (box-wide); skipped"), "breaker_open", True),
                                  (ArchiveTimeout("wayback giving up on u after 2 timeout/network failure(s)"), "timeout", True),
                                  (ArchiveError("wayback cdx 404", status=404), "wb_failed", False)):
        f.wb_captures = lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e)
        r = f.list_captures("x.org/")
        assert isinstance(r, CaptureList) and r.truncated and r.truncated_reason == reason, (reason, r.truncated_reason)
        assert (r.deferral is not None) == deferred and r.errors
        if deferred:
            assert r.deferral.reason == reason
            if reason == "breaker_open":
                assert r.deferral.retry_in >= 55
    f.wb_captures = lambda *a, **k: (_ for _ in ()).throw(ArchiveBreakerOpen("wayback breaker open"))
    try:
        f.list_captures("x.org/", on_deferred="raise"); assert False
    except ArchiveDeferred as e:
        assert e.reason == "breaker_open" and e.partial == []
    # CC truncation propagates into list_captures
    g = fx()
    g.cc_crawls = lambda: ["A"]
    g._cc_query = lambda *a, **k: (_ for _ in ()).throw(ArchiveError("cc page 404", status=404))
    g.wb_captures = lambda *a, **k: list(WB)
    r = g.list_captures("x.org/")
    assert r.truncated and r.truncated_reason == "crawl_failed" and len(r) == 1 and any(e.startswith("cc:") for e in r.errors)
    print("ok 2 list_captures: Wayback breaker / timeout / error and CC failures flag .truncated with reason")


def test_fetch_best_no_false_miss():
    f = fx()
    f.fetch_capture = lambda c: (_ for _ in ()).throw(ArchiveTimeout("cc_data giving up on x after 2 timeout/network failure(s)"))
    try:
        f.fetch_best(CC); assert False
    except ArchiveDeferred as e:
        assert e.reason == "timeout" and e.families == ["cc_data"] and e.retry_in >= 55
        assert isinstance(e.fetch_info, FetchInfo) and e.fetch_info.cc_deferred == 2 and len(e.fetch_info.errors) == 1 and e.fetch_info.skipped == {"commoncrawl": 1}
    assert f.fetch_best(CC, raise_deferred=False) is None
    f.fetch_capture = lambda c: (_ for _ in ()).throw(ArchiveError("cc_data http 404", status=404))
    assert f.fetch_best(CC + WB) is None                  # every source answered: genuine miss
    # fetch_newest: Wayback CDX breaker-open + CC miss -> deferred, not None
    f.cc_crawls = lambda: ["A"]
    f._cc_query = lambda *a, **k: []
    f.wb_captures = lambda *a, **k: (_ for _ in ()).throw(ArchiveBreakerOpen("wayback breaker open (box-wide); skipped"))
    try:
        f.fetch_newest("https://x.org/a"); assert False
    except ArchiveDeferred as e:
        assert e.reason == "breaker_open"
    print("ok 3 fetch_best/fetch_newest: timeouts / breaker -> ArchiveDeferred; None only for genuine misses")


def test_doc_incomplete_signal():
    f = fx()

    def fc(cap):
        if cap.source == "commoncrawl":
            raise ArchiveTimeout("cc_data giving up after 2 timeout/network failure(s)")
        return doc("wayback")
    f.fetch_capture = fc
    d = f.fetch_best(CC + WB)
    assert isinstance(d, ArchivedDoc) and d.incomplete and d.deferral.families == ["cc_data"]
    assert d.fetch_info.incomplete and d.fetch_info.cc_deferred == 2 and d.content_complete
    f.fetch_capture = lambda c: doc(c.source)
    d2 = f.fetch_best(CC + WB)
    assert d2.incomplete is False and d2.deferral is None and not d2.fetch_info.incomplete
    from dataclasses import asdict
    assert "fetch_info" not in asdict(d2) and "incomplete" not in asdict(d2)      # not cached / not a field
    print("ok 4 doc found while another source failed: doc.incomplete / doc.deferral / doc.fetch_info")


def test_nested_context():
    f = fx()
    inner = fx()

    def fc(cap):
        if cap.source == "commoncrawl":
            raise ArchiveDeferred("cc 429", family="cc_data", host="data.commoncrawl.org", status=429,
                                  not_before=time.time() + 300)
        return doc("wayback")
    f.fetch_capture = fc

    def validator(d):                                    # a builder doing a nested clean fetch on the SAME fetcher
        save = f.fetch_capture
        f.fetch_capture = lambda c: doc("commoncrawl")
        f.fetch_best([CC[0]])                            # overwrites f.last_* with a clean result
        assert f.last_deferral is None               # instance attr now describes the nested call
        f.fetch_capture = save
        return True
    d = f.fetch_best(CC + WB, validator=validator)
    assert d.incomplete and d.fetch_info.deferral.families == ["cc_data"]   # ... per-call context is not
    d3, info = f.fetch_best_ex(CC, validator=None)
    assert d3 is None and info.exception is not None and info.exception.fetch_info is info
    d4, info4 = f.fetch_best_ex(WB)
    assert d4 is not None and not info4.incomplete and d4.fetch_info is info4
    del inner
    print("ok 5 per-call context survives nested calls; fetch_best_ex returns (doc, info)")


if __name__ == "__main__":
    test_cc_captures_truncation()
    test_list_captures_wayback_failures()
    test_fetch_best_no_false_miss()
    test_doc_incomplete_signal()
    test_nested_context()
    print("ALL OK test_archive_deferral3")
