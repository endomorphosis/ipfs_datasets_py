"""Offline check of the ukie ArchiveDeferred handling (no network, temp rate-limit dir, temp state db).
Run: /workspace/world_law/pipeline/venv/bin/python tests/test_archive_defer.py   (from scrapers/ukie)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import io, re, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ratelimit as rl, deferral  # noqa: E402
import requests, urllib3  # noqa: E402

rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="ukie_defer_rl_"))     # never the box-wide state
deferral._sleep = lambda s: None
from archive import ArchiveFetcher  # noqa: E402
import councils  # noqa: E402
from common.util import State  # noqa: E402

CALLS = []


def resp(status, body=b"", headers=None, url="https://web.archive.org/x"):
    r = requests.models.Response()
    r.status_code, r.url = status, url
    r.headers.update(headers or {})
    r.raw = urllib3.HTTPResponse(body=io.BytesIO(body), preload_content=False, status=status)
    return r


def mkfx(mode):
    fx = ArchiveFetcher(cache_dir=tempfile.mkdtemp(prefix="ukie_defer_cache_"), use_cc=False, lane="ukie_test")
    fx.s.get = lambda url, **k: (CALLS.append(url), resp(429, headers={"Retry-After": "120"}) if mode == "429"
                                 else resp(200, b"[]", {"Content-Type": "application/json"}))[1]
    councils.DeferTracker(fx)
    return fx


st = State(Path(tempfile.mkdtemp(prefix="ukie_defer_db_")) / "s.sqlite")
row = {"place_id": "wd:QTEST", "place_name": "Test Council", "site": "https://www.example-council.gov.uk",
       "country_code": "GB", "qid": "QTEST", "admin_level": 8, "phase": 3}

# 1) 429 during archive discovery -> one real request, rest skipped by the host cool-down, place requeued
fx = mkfx("429")
c = councils.Council(row, None, st, {}, 8); c.mode = "archive"
t0 = time.time()
c.run_archive(fx)
assert len(CALLS) == 1, CALLS                                   # no in-process retry of the 429
assert councils.DISCOVER_KEY in c.deferred, c.deferred
nb = st.place_not_before("wd:QTEST")
assert nb and 110 < nb - t0 < 135, nb - t0                      # Retry-After 120 honoured
assert time.time() - t0 < 30                                    # no sleeping out the cool-down
print("1 ok: discovery deferred, not_before +%.0fs, %d request(s)" % (nb - t0, len(CALLS)))

# 2) archive_call: deferral swallowed by fetch_newest is still seen (cool-down -> immediate ArchiveDeferred)
doc, d = councils.archive_call(fx, fx.fetch_newest, "https://www.example-council.gov.uk/byelaws.pdf")
assert doc is None and d and d.not_before >= nb - 1 and d.host == "web.archive.org", vars(d) if d else d
assert len(CALLS) == 1
print("2 ok: fetch_newest during cool-down -> Deferral until +%.0fs, no request" % (d.not_before - t0))

# 3) robots-disallowed doc deferred, then re-visited after the cool-down (fresh limiter dir = cool-down over)
c.robots_doc_archive(fx, "https://www.example-council.gov.uk/b.pdf", "Byelaws", "byelaw", "robots: disallow")
rows = [r for r in st.pending_deferrals("wd:QTEST") if r["key"].endswith("b.pdf")]
assert rows and rows[0]["info"]["kind"] == "robots_doc"
rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="ukie_defer_rl2_"))
fx2 = mkfx("ok")
c2 = councils.Council(row, None, st, {}, 8)
c2.run_deferred_docs(fx2, rows)
assert not c2.deferred
assert st.doc_done("wd:QTEST", "ukbyelaw:" + councils.doc_key("https://www.example-council.gov.uk/b.pdf")) \
    == "deferred:robots_no_archive"
print("3 ok: re-visited doc resolved (not archived -> deferred:robots_no_archive)")

# 4) full archive pass with the archive answering: discovery resolves, nothing pending -> not 'deferred'
t1 = time.time()
c3 = councils.Council(row, None, st, {}, 8); c3.mode = "archive"
c3.run_archive(fx2)
st.supersede_deferrals("wd:QTEST", t1)
assert not c3.deferred and st.place_not_before("wd:QTEST") is None, st.pending_deferrals("wd:QTEST")
print("4 ok: clean pass clears the requeue (rows kept as resolved/superseded, none deleted):",
      st.c.execute("SELECT state, COUNT(*) FROM archive_deferrals GROUP BY state").fetchall())

# 5) parish selection: robots disallow / TLS yes; HTTP 403 and plain timeouts no
P = councils.PARISH_ARCHIVE_BASIS
for b, want in [("robots.txt error SSLError => disallow", True), ("robots.txt 404 => disallow", True),
                ("robots.txt 200 => disallow", True), ("home failed: SSLError(certificate verify failed)", True),
                ("HTTP 403", False), ("home failed: HTTP 503", False),
                ("robots.txt error ConnectTimeout => disallow", False)]:
    assert bool(P.search(b)) == want, (b, want)
print("5 ok: parish archive selection rule")
# 6) truncated listing (CaptureList.truncated) -> partial result kept, but a Deferral is returned
from archive.core import CaptureList, ArchiveDeferred, Capture
nbx = time.time() + 300
part = CaptureList([Capture("wayback", "wayback", "20250101000000", "https://x/byelaws.pdf", 200, "application/pdf",
                            None, 10)]).flag(ArchiveDeferred("cc deferred", host="index.commoncrawl.org", not_before=nbx))
res, d = councils.archive_call(fx2, lambda: part)
assert len(res) == 1 and d and abs(d.not_before - nbx) < 1, d
# 7) merged ArchiveDeferred raised by fetch_* -> Deferral; None with nothing deferred -> genuine miss
def boom():
    raise ArchiveDeferred("merged", host="web.archive.org", not_before=nbx)
res, d = councils.archive_call(fx2, boom)
assert res is None and d and d.not_before >= nbx - 0.01
res, d = councils.archive_call(fx2, lambda: None)
assert res is None and d is None
print("6/7 ok: truncated listing and merged raise handled; None = genuine miss")

# 8) round 3: doc.incomplete -> staged AND requeued; place stays pending; complete refetch re-stages + resolves
from archive.core import ArchivedDoc
import archive.core as ac
U = "https://www.example-council.gov.uk/inc.pdf"
def mkdoc(incomplete):
    dd = ArchivedDoc(original_url=U, archive_source="commoncrawl", archive_crawl_id="CC-MAIN-2026-39",
                     archive_timestamp="2026-09-01T00:00:00Z", archive_url="https://data.commoncrawl.org/x",
                     http_status=200, content_type="application/pdf", body=b"%PDF-1.4 test")
    if incomplete:
        dd.incomplete = True
        dd.deferral = ArchiveDeferred("wayback timeout", host="web.archive.org", not_before=time.time() + 400,
                                      reason="timeout")
    return dd
emitted = []
c4 = councils.Council(dict(row, place_id="wd:QINC"), None, st, {}, 8)
c4.emit = lambda u, t, body, kind, prov=None, **k: (emitted.append(u), st.mark_doc("wd:QINC", "ukbyelaw:" +
                                                    councils.doc_key(u), u, "staged"))
fxi = mkfx("ok"); fxi.fetch_newest = lambda u, **k: mkdoc(True)
c4.robots_doc_archive(fxi, U, "Inc byelaws", "byelaw", "robots: disallow")
assert emitted == [U], emitted                                   # incomplete doc IS staged
pend = st.pending_deferrals("wd:QINC")
assert len(pend) == 1 and pend[0]["info"].get("incomplete") and pend[0]["not_before"] > time.time() + 300, pend
assert st.place_not_before("wd:QINC") is not None                # -> main() marks the place 'deferred', not done
# revisit, still incomplete: not re-staged, still pending
c5 = councils.Council(dict(row, place_id="wd:QINC"), None, st, {}, 8); c5.emit = c4.emit
c5.run_deferred_docs(fxi, pend)
assert emitted == [U] and st.pending_incomplete("wd:QINC", U)
# revisit, complete: doc_done says staged but the incomplete requeue forces a refetch; re-staged and resolved
fxi.fetch_newest = lambda u, **k: mkdoc(False)
c6 = councils.Council(dict(row, place_id="wd:QINC"), None, st, {}, 8); c6.emit = c4.emit
c6.run_deferred_docs(fxi, st.pending_deferrals("wd:QINC"))
assert emitted == [U, U] and st.place_not_before("wd:QINC") is None, (emitted, st.pending_deferrals("wd:QINC"))
print("8 ok: incomplete doc staged + requeued (place pending); complete refetch re-staged and resolved")

# 9) listing with only permanent gaps -> final; retryable gap -> deferred
perm = CaptureList([]); perm.truncated = True; perm.truncated_reason = "crawl_failed"
assert councils.archive_call(fx2, lambda: perm)[1] is None
retry = CaptureList([]).flag(ArchiveDeferred("cc_breaker", host="index.commoncrawl.org", not_before=nbx,
                                             reason="cc_breaker"))
assert councils.archive_call(fx2, lambda: retry)[1].not_before >= nbx - 0.01
# 10) typed transient (timeout after retry budget) escaping -> requeue, not a miss
def to():
    raise ac.ArchiveTimeout("wayback timeout")
res, d = councils.archive_call(fx2, to)
assert res is None and d and d.not_before > time.time() + 60
print("9/10 ok: permanent-only truncation final, retryable truncation and ArchiveTimeout requeued")
print("ALL OK")
