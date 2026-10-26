"""Round 5 (2026-10-18): conservative permanence. A plain ArchiveError / parse error / code bug is a retryable gap
(unknown_error, retry in 1 h); only explicit 400/404/410 (and Wayback 403) are permanent; any 403 from
*.commoncrawl.org is throttling (deferral), never permanent. Mocked HTTP, temp RATE_DIR, no network.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_archive_deferral5.py
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
from archive.core import ArchiveFetcher, ArchiveDeferred, ArchiveError, ArchiveTimeout, Capture  # noqa: E402

rl.FAMILIES.update(wayback=0.0, cc_index=0.0, cc_data=0.0)
dfr.LANE_MIN_INTERVAL = 0.0
rl.SOFT_BASE = rl.SOFT_MAX = rl.BASE_BACKOFF = 0.01


def fx(**kw):
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="def5_rl_"))
    return ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="def5_c_"), lane="t", **kw)


def resp(code):
    r = requests.Response()
    r.status_code, r.raw, r.url = code, None, ""
    r.headers.update({})
    return r


def test_permanence_flags():
    assert not ArchiveError("x").permanent                        # no status: NOT permanent any more
    assert all(ArchiveError("x", status=c).permanent for c in (400, 404, 410))
    assert not any(ArchiveError("x", status=c).permanent for c in (401, 403, 408, 429, 500, 503))
    assert ArchiveError("x", status=403, permanent=True).permanent and not ArchiveTimeout("t").permanent
    print("ok permanent only for 400/404/410 or explicit permanent=True")


def test_unknown_errors_are_retryable_gaps():
    f = fx()
    f.cc_crawls = lambda: ["A", "B"]
    f._cc_query = lambda crawl, *a, **k: ((_ for _ in ()).throw(ArchiveError("cc weird")) if crawl == "A" else [])
    r = f.cc_captures("x.org/")
    assert r.truncated and r.retryable_truncation and not r.complete_except_permanent
    assert r.deferral.reason == "unknown_error" and 3500 < r.deferral.retry_in <= 3600
    f._cc_query = lambda crawl, *a, **k: {}["boom"]               # code bug: a gap, not a crash
    r = f.cc_captures("x.org/")
    assert r.retryable_truncation and any("KeyError" in e for e in r.errors)
    f.cc_crawls = lambda: (_ for _ in ()).throw(ValueError("bad json"))
    r = f.cc_captures("x.org/")
    assert r.truncated_reason == "crawl_list_unavailable" and r.retryable_truncation
    f.cc_crawls = lambda: (_ for _ in ()).throw(ArchiveError("cc collinfo 404", status=404))
    assert f.cc_captures("x.org/").complete_except_permanent
    g = fx(use_cc=False)                                          # Wayback CDX unknown error -> retryable
    g.wb_captures = lambda *a, **k: (_ for _ in ()).throw(ArchiveError("cdx odd"))
    r = g.list_captures("x.org/")
    assert r.truncated_reason == "wb_failed" and r.retryable_truncation
    print("ok unknown / parse / code-bug errors -> retryable gap (unknown_error, 1 h)")


def test_cc_403_is_throttling():
    for host, call in (("index", lambda f: f._cc_query("CC-MAIN-2026-39", "x.org/", "prefix")),
                       ("data", lambda f: f.fetch_cc(Capture("commoncrawl", "C", "20250101000000", "https://x.org/a",
                                                             200, None, None, 100, "f.warc.gz", 1)))):
        f = fx()
        f.cc_crawls = lambda: ["CC-MAIN-2026-39"]
        f.s.get = lambda url, **kw: resp(403)
        try:
            call(f); assert False
        except ArchiveDeferred as e:
            assert e.status == 403 and e.retry_in > 0 and e.host.endswith("commoncrawl.org"), host
    f = fx()
    f.cc_crawls = lambda: ["CC-MAIN-2026-39"]
    f.s.get = lambda url, **kw: resp(403)
    r = f.cc_captures("x.org/")
    assert r.retryable_truncation and r.deferral.status == 403
    print("ok 403 from index./data.commoncrawl.org -> ArchiveDeferred (throttling), listing retryable")


def test_wayback_403_kept_permanent():
    f = fx(use_cc=False)
    f.s.get = lambda url, **kw: resp(403)
    wb = Capture("wayback", "wayback", "20240101000000", "https://x.org/a", 200)
    try:
        f.fetch_wayback(wb); assert False
    except ArchiveDeferred:
        assert False
    except ArchiveError as e:
        assert e.status == 403 and e.permanent
    assert f.fetch_best([wb]) is None                             # genuine miss (excluded by site owner)
    print("ok Wayback 403 unchanged: permanent for that URL, not a deferral")


if __name__ == "__main__":
    test_permanence_flags()
    test_unknown_errors_are_retryable_gaps()
    test_cc_403_is_throttling()
    test_wayback_403_kept_permanent()
    print("ALL OK test_archive_deferral5")
