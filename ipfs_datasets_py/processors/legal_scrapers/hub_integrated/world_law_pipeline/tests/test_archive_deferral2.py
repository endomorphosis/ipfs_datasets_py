"""ArchiveFetcher deferral surfacing (2026-10-18 follow-up): fetch_best / fetch_newest raise one merged ArchiveDeferred
when nothing usable was found and a source was deferred (genuine miss -> None; raise_deferred=False -> old None),
expose last_deferral / last_cc_deferred / last_wb_deferred when a doc is found anyway; cc_captures / list_captures
return a CaptureList flagged deferred/truncated (or raise with .partial); timeouts retried at most timeout_retries
(default 1) and still counted toward the Wayback breaker. Mocked, temp RATE_DIR.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_archive_deferral2.py
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
import requests  # noqa: E402
from archive import ratelimit as rl, deferral as dfr  # noqa: E402
from archive.core import (ArchiveFetcher, ArchiveDeferred, ArchiveTransient, ArchivedDoc, Capture,  # noqa: E402
                          CaptureList, ArchiveError)

rl.FAMILIES.update(wayback=0.0, cc_index=0.0, cc_data=0.0)
rl.SOFT_BASE, rl.SOFT_MAX = 0.05, 0.1
dfr.LANE_MIN_INTERVAL = 0.0


def fx(**kw):
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="def2_rl_"))
    return ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="def2_c_"), lane="t", **kw)


def D(fam, host, secs):
    return ArchiveDeferred(f"{fam} 429", family=fam, host=host, status=429, not_before=time.time() + secs)


def doc(src):
    return ArchivedDoc("https://x.org/a", src, "c", "2026-01-01T00:00:00Z", "u", 200, "text/html",
                       body=b"<html><body>" + b"law text " * 50 + b"</body></html>")


CC = [Capture("commoncrawl", "CC-MAIN-2026-39", f"2025010{i}000000", "https://x.org/a", 200, None, None, None,
              "f.warc.gz", 1) for i in range(1, 4)]
WB = [Capture("wayback", "wayback", f"2024010{i}000000", "https://x.org/a", 200) for i in range(1, 3)]


def test_fetch_best():
    f = fx()
    calls = []

    def fc(cap, wb_result):
        calls.append(cap.source)
        if cap.source == "commoncrawl":
            raise D("cc_data", "data.commoncrawl.org", 300)
        if wb_result == "defer":
            raise D("wayback", "web.archive.org", 120)
        if wb_result == "miss":
            raise ArchiveError("wayback replay http 404")
        return doc("wayback")
    # CC deferred + Wayback genuine miss -> merged ArchiveDeferred (cc only), CC skipped after first deferral
    f.fetch_capture = lambda c: fc(c, "miss")
    try:
        f.fetch_best(CC + WB); assert False
    except ArchiveDeferred as e:
        assert isinstance(e, ArchiveTransient) and e.families == ["cc_data"] and e.sources == ["commoncrawl"]
        assert e.host == "data.commoncrawl.org" and 295 < e.retry_in <= 300
    assert calls == ["commoncrawl", "wayback", "wayback"] and f.last_cc_deferred == 3
    # both deferred -> earliest not_before (wayback 120 s), both families/hosts
    calls.clear(); f.fetch_capture = lambda c: fc(c, "defer")
    try:
        f.fetch_best(CC + WB); assert False
    except ArchiveDeferred as e:
        assert e.families == ["cc_data", "wayback"] and e.hosts == ["data.commoncrawl.org", "web.archive.org"]
        assert e.host == "web.archive.org" and 115 < e.retry_in <= 120
    assert calls == ["commoncrawl", "wayback"] and f.last_wb_deferred == 2
    # deferrals don't use up max_tries; doc found from the other source is returned + deferral exposed
    calls.clear(); f.fetch_capture = lambda c: fc(c, "ok")
    d = f.fetch_best(CC + WB, max_tries=1)
    assert d is not None and d.archive_source == "wayback" and f.last_cc_deferred == 3
    assert f.last_deferral is not None and f.last_deferral.families == ["cc_data"]
    # genuine miss -> None, no deferral
    f.fetch_capture = lambda c: (_ for _ in ()).throw(ArchiveError("404"))
    assert f.fetch_best(CC + WB) is None and f.last_deferral is None and f.last_cc_deferred == 0
    # opt-out: per call and per fetcher
    f.fetch_capture = lambda c: fc(c, "miss")
    assert f.fetch_best(CC + WB, raise_deferred=False) is None and f.last_deferral is not None
    g = fx(raise_deferred=False)
    g.fetch_capture = lambda c: fc(c, "miss")
    assert g.fetch_best(CC + WB) is None and g.last_cc_deferred == 3
    print("ok fetch_best: raise merged deferral / return doc + last_deferral / None on miss / opt-out")


def test_cc_captures_and_list():
    f = fx()
    f.cc_crawls = lambda: ["A", "B", "C"]
    seen = []

    def q(crawl, url, match, filters=None, **kw):
        seen.append(crawl)
        if crawl == "B":
            raise D("cc_index", "index.commoncrawl.org", 60)
        return [CC[0]]
    f._cc_query = q
    got = f.cc_captures("x.org/", "prefix")
    assert isinstance(got, CaptureList) and isinstance(got, list) and len(got) == 1
    assert got.deferred and got.truncated and got.deferral.families == ["cc_index"] and seen == ["A", "B"]
    assert f.last_cc_deferred == 1
    seen.clear()
    try:
        f.cc_captures("x.org/", "prefix", on_deferred="raise"); assert False
    except ArchiveDeferred as e:
        assert e.partial == [CC[0]]
    try:
        f.cc_captures("x.org/", "prefix", on_error="raise"); assert False
    except ArchiveDeferred:
        pass
    f._cc_query = lambda crawl, url, match, filters=None, **kw: [CC[0]]
    ok = f.cc_captures("x.org/")
    assert not ok.deferred and ok.deferral is None and len(ok) == 3
    # list_captures: Wayback CDX deferral -> flagged, not an ordinary logged error
    f.wb_captures = lambda *a, **k: (_ for _ in ()).throw(D("wayback", "web.archive.org", 90))
    lc = f.list_captures("x.org/")
    assert lc.deferred and lc.truncated and lc.deferral.families == ["wayback"] and len(lc) == 3
    try:
        f.list_captures("x.org/", on_deferred="raise"); assert False
    except ArchiveDeferred as e:
        assert len(e.partial) == 3
    h = fx(listing_deferred="raise")
    h.cc_crawls = lambda: ["A"]
    h._cc_query = lambda *a, **k: (_ for _ in ()).throw(D("cc_index", "index.commoncrawl.org", 60))
    try:
        h.cc_captures("x.org/"); assert False
    except ArchiveDeferred:
        pass
    print("ok cc_captures / list_captures flag or raise on deferral (no silent truncation)")


def test_fetch_newest():
    f = fx()
    f.cc_crawls = lambda: ["A"]
    f._cc_query = lambda *a, **k: (_ for _ in ()).throw(D("cc_index", "index.commoncrawl.org", 200))
    f.wb_captures = lambda *a, **k: []                 # genuine: Wayback has nothing
    try:
        f.fetch_newest("https://x.org/a"); assert False
    except ArchiveDeferred as e:
        assert e.families == ["cc_index"]
    assert f.fetch_newest("https://x.org/a", raise_deferred=False) is None and f.last_cc_deferred == 1
    f.wb_captures = lambda *a, **k: (_ for _ in ()).throw(D("wayback", "web.archive.org", 100))
    try:
        f.fetch_newest("https://x.org/a"); assert False
    except ArchiveDeferred as e:
        assert e.families == ["cc_index", "wayback"] and 95 < e.retry_in <= 100
    assert f.last_wb_deferred == 1
    # CC listing deferred but Wayback finds it -> doc returned, deferral exposed
    f.wb_captures = lambda *a, **k: [WB[0]]
    f.fetch_capture = lambda c: doc("wayback")
    d = f.fetch_newest("https://x.org/a")
    assert d is not None and f.last_deferral.families == ["cc_index"] and f.last_cc_deferred == 1
    # genuine miss everywhere -> None
    f._cc_query = lambda *a, **k: []
    f.wb_captures = lambda *a, **k: []
    assert f.fetch_newest("https://x.org/a") is None and f.last_deferral is None
    print("ok fetch_newest: CDX + capture deferrals merged, doc-despite-deferral, None on miss")


def test_timeout_retries():
    for tr, want in ((None, 2), (0, 1), (3, 4)):
        f = fx(timeout_retries=tr) if tr is not None else fx()
        n = []

        def get(url, **kw):
            n.append(1)
            raise requests.Timeout("read timed out")
        f.s.get = get
        try:
            f._get("cc_data", "https://data.commoncrawl.org/crawl-data/x.warc.gz"); assert False
        except ArchiveDeferred:
            assert False, "a timeout is not a deferral"
        except ArchiveTransient as e:
            assert "timeout" in str(e)
        assert len(n) == want, (tr, len(n))
    f = fx()                                       # Wayback: default 1 retry, both timeouts hit the breaker count
    n = []
    f.s.get = lambda url, **kw: (n.append(1), (_ for _ in ()).throw(requests.Timeout("t")))[1]
    try:
        f._get("wayback", "https://web.archive.org/web/2020id_/https://x.org/a"); assert False
    except ArchiveTransient:
        pass
    assert len(n) == 2 and int(rl.breaker_status().get("consec_fails", 0)) == 2
    print("ok timeouts: default 1 retry (configurable), still counted toward the breaker")


if __name__ == "__main__":
    test_fetch_best()
    test_cc_captures_and_list()
    test_fetch_newest()
    test_timeout_retries()
    print("ALL OK test_archive_deferral2")
