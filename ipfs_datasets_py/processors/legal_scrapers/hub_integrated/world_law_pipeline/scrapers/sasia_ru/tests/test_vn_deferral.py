"""Offline tests (no network, temp dirs only) for the VN ArchiveDeferred handling (2026-10-18).
Run: ARCHIVE_LANE=sasia_ru /workspace/world_law/pipeline/venv/bin/python tests/test_vn_deferral.py"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, io, json, time, tempfile, importlib
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/sasia_ru"))
from archive import ratelimit as rl, deferral, core
from archive.core import ArchiveDeferred, ArchiveTransient, ArchiveError, Capture, ArchivedDoc, ArchiveFetcher

_TD = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_ru/_test_deferral"); os.makedirs(_TD, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="vn_defer_test_", dir=_TD))
rl.RATE_DIR = TMP / "_ratelimit"           # never touch the live _ratelimit
deferral.LANE_MIN_INTERVAL = 0.0

t0 = time.time()
import vn_vbpl_archive as V                 # must NOT run main() on import
import vn_driver as DR                      # must NOT start the driver loop on import
assert time.time() - t0 < 5, "import started work"
assert not os.path.exists(TMP / "x")

BODY = ('<html><div class="fulltext"><span>Hiệu lực: </span> Còn hiệu lực<br>'
        '<span>Ngày có hiệu lực: </span> 01/02/2020<br>ỦY BAN NHÂN DÂN TỈNH PHÚ YÊN<br>Số: 12/2020/QĐ-UBND<br>'
        'Phú Yên, ngày 5 tháng 1 năm 2020</div><div id="toanvancontent"><p>QUYẾT ĐỊNH</p><p>Ban hành quy định</p>'
        + "<p>" + ("Điều khoản nội dung quy định về quản lý. " * 20) + "</p></div><div class=\"vbProperties\"></div></html>").encode()

def cap(i):
    return Capture("wayback", "wayback", "20240101000000", f"https://vbpl.vn/phuyen/Pages/vbpq-toanvan.aspx?ItemID={i}", 200, "text/html", None, None)

def doc(c):
    return ArchivedDoc(original_url=c.original_url, archive_source="wayback", archive_crawl_id="wayback",
                       archive_timestamp="2024-01-01T00:00:00Z", archive_url=f"https://web.archive.org/web/{c.timestamp}id_/{c.original_url}",
                       http_status=200, content_type="text/html", body=BODY, content_complete=True, incomplete_reason=None, possibly_stale=False)

class FakeFX:
    """Fake fetcher: items in `defer` raise ArchiveDeferred, items in `breaker` raise ArchiveTransient, `gone` -> ArchiveError."""
    def __init__(self, n=5, defer=(), breaker=(), gone=(), cdx_exc=None):
        self.caps = [cap(i) for i in range(1, n + 1)]; self.defer, self.breaker, self.gone, self.cdx_exc = set(defer), set(breaker), set(gone), cdx_exc
        self.fetched = []
    def wb_captures(self, *a, **k):
        if self.cdx_exc: raise self.cdx_exc
        return list(self.caps)
    def fetch_capture(self, c):
        i = int(c.original_url.rsplit("=", 1)[1]); self.fetched.append(i)
        if i in self.defer: raise ArchiveDeferred("wayback 429", url=c.original_url, host="web.archive.org", status=429, not_before=time.time() + 120)
        if i in self.breaker: raise ArchiveTransient("wayback giving up (slot busy / backing off): wayback breaker open")
        if i in self.gone: raise ArchiveError("wayback replay http 404")
        return doc(c)

NOW = "2026-10-18T19:00:00Z"
def pp(fx, per=40): return V.process_place(fx, "phuyen", "iso:VN-32", "Phú Yên", "adm1", per, NOW)

# 1 complete
recs, st = pp(FakeFX(5)); assert st["status"] == "complete" and len(recs) == 5 and not st["deferred"], st
# 2 one item deferred -> other items still processed, status deferred, not_before set
fx = FakeFX(5, defer={3}); recs, st = pp(fx)
assert st["status"] == "deferred" and len(recs) == 4 and sorted(fx.fetched) == [1, 2, 3, 4, 5], (st, fx.fetched)
assert [d["item"] for d in st["deferred"]] == ["3"] and st["not_before"] > time.time() + 100
assert fx.fetched.count(3) == 1                                             # no in-place retry
# 3 all deferred -> empty result is NOT 'complete/empty'
recs, st = pp(FakeFX(4, defer={1, 2, 3, 4})); assert st["status"] == "deferred" and recs == [] and len(st["deferred"]) == 4
# 4 CDX listing deferred -> deferred, not empty
recs, st = pp(FakeFX(cdx_exc=ArchiveDeferred("cooling", host="web.archive.org", not_before=time.time() + 60)))
assert st["status"] == "deferred" and st["deferred"][0]["item"] == "__cdx__"
# 5 breaker on CDX / item -> 'breaker'
recs, st = pp(FakeFX(cdx_exc=ArchiveTransient("wayback breaker open (box-wide); skipped"))); assert st["status"] == "breaker", st
recs, st = pp(FakeFX(3, breaker={2})); assert st["status"] == "breaker" and len(recs) == 2, st
# 6 permanent 404 is a real miss (complete); permanent CDX error keeps old 'cdx_error'
recs, st = pp(FakeFX(3, gone={2})); assert st["status"] == "complete" and len(recs) == 2
recs, st = pp(FakeFX(cdx_exc=ArchiveError("wayback cdx 403"))); assert st["status"] == "cdx_error"
# 7 deferred items don't eat the per-place budget; per_place cap still respected
recs, st = pp(FakeFX(10, defer={10, 9}), per=3); assert len(recs) == 3 and st["status"] == "deferred"
print("ok process_place (fake fetcher)")

# 8 real ArchiveFetcher plumbing with a fake HTTP session: 503 -> ArchiveDeferred + host cool-down, then immediate deferral
class Raw:
    def __init__(self, b): self.b = io.BytesIO(b)
    def read(self, n=-1, decode_content=False): return self.b.read(n)
class Sess:
    def __init__(self, plan): self.plan, self.calls = list(plan), []
    def get(self, url, **k):
        self.calls.append(url); code, hdr, body = self.plan.pop(0)
        import requests
        r = requests.Response(); r.status_code = code; r.headers.update(hdr); r.raw = Raw(body); r.url = url; return r
fx = ArchiveFetcher(cache_dir=str(TMP / "cache"), use_cc=False, lane="sasia_ru_test")
assert fx.defer_on_throttle
fx.s = Sess([(503, {}, b"busy")])
recs, st = pp(fx)
assert st["status"] == "deferred" and st["deferred"][0]["item"] == "__cdx__" and 55 < st["not_before"] - time.time() <= 61, st
assert len(fx.s.calls) == 1 and deferral.host_cooldown("web.archive.org") > 50
recs, st = pp(fx); assert st["status"] == "deferred" and len(fx.s.calls) == 1       # cooling: no request at all
br = rl.breaker_status() if hasattr(rl, "breaker_status") else {}
assert int(br.get("consec_fails", 0) or 0) == 0, br                                    # deferral is not a breaker failure
# cool-down over, CDX ok, item 1 replay -> 429 Retry-After 30, item 2 -> cooling (no request)
d = json.loads((rl.RATE_DIR / "host_cooldown.json").read_text()); d["web.archive.org"]["not_before"] = 0; (rl.RATE_DIR / "host_cooldown.json").write_text(json.dumps(d))
cdx = json.dumps([["timestamp", "original", "mimetype", "statuscode", "digest", "length"],
                  ["20240101000000", "https://vbpl.vn/phuyen/Pages/vbpq-toanvan.aspx?ItemID=1", "text/html", "200", "x", "100"],
                  ["20240101000000", "https://vbpl.vn/phuyen/Pages/vbpq-toanvan.aspx?ItemID=2", "text/html", "200", "y", "100"]]).encode()
fx.s = Sess([(200, {}, cdx), (429, {"Retry-After": "30"}, b"")])
recs, st = pp(fx)
assert st["status"] == "deferred" and {x["item"] for x in st["deferred"]} == {"1", "2"} and len(fx.s.calls) == 2, (st, fx.s.calls)
assert 25 < st["not_before"] - time.time() <= 31
# after not_before: CDX from cache, both bodies fetched -> complete
d = json.loads((rl.RATE_DIR / "host_cooldown.json").read_text()); d["web.archive.org"]["not_before"] = 0; (rl.RATE_DIR / "host_cooldown.json").write_text(json.dumps(d))
fx.s = Sess([(200, {"Content-Type": "text/html"}, BODY), (200, {"Content-Type": "text/html"}, BODY)])
recs, st = pp(fx); assert st["status"] == "complete" and len(recs) == 2 and len(fx.s.calls) == 2, (st, fx.s.calls)
print("ok real ArchiveFetcher + fake HTTP (503/429 -> deferred, cool-down short-circuit, revisit completes)")

# 9 driver: deferred province not marked done, others continue, revisit after not_before, persisted queue, breaker wait
D = str(TMP / "drv") + "/"; os.makedirs(D)
open(D + "vn_done.txt", "w").write("aa\n")
clock = [1000.0]; sleeps = []
script = {"bb": [{"status": "deferred", "docs": 2, "deferred": [{"item": "7", "url": "u7", "not_before": 1100.0, "reason": "deferred"}], "not_before": 1100.0},
                 {"status": "complete", "docs": 3, "deferred": []}],
          "cc": [{"status": "deferred", "docs": 0, "deferred": [{"item": "__cdx__", "url": "c", "not_before": 1050.0, "reason": "deferred"}], "not_before": 1050.0},
                 {"status": "complete", "docs": 0, "deferred": []}],
          "dd": [None, {"status": "breaker", "docs": 1, "deferred": [{"item": "1", "url": "x", "not_before": 0, "reason": "breaker"}]},
                 {"status": "complete", "docs": 5, "deferred": []}]}
calls = []
def runner(s, d):
    calls.append((s, clock[0])); st = script[s].pop(0)
    return (1 if st is None else 0), st, ("staged ['x']" if st and st["status"] == "complete" and st["docs"] else "")
def sleep(x): sleeps.append(x); clock[0] += x
done_mid = {}
def runner2(s, d):
    r = runner(s, d)
    done_mid[len(calls)] = (open(D + "vn_done.txt").read().split(), [json.loads(l)["slug"] for l in open(D + "vn_deferred.jsonl")])
    return r
DR.CHILD_ERROR_RETRY_S = 200
res = DR.drive(["aa", "bb", "cc", "dd"], d=D, runner=runner2, wb_available=lambda: True, host_cooldown=lambda: 0.0,
               sleep=sleep, clock=lambda: clock[0], max_loops=50)
assert res == "finished", res
order = [c[0] for c in calls]
assert order[:3] == ["bb", "cc", "dd"], order                      # moved on after deferrals
assert "aa" not in order
assert done_mid[1] == (["aa"], []) and done_mid[2][0] == ["aa"] and "bb" in done_mid[2][1]   # bb deferred, not done
for s, t in calls:
    if s == "bb" and t > 1000: assert t >= 1100
    if s == "cc" and t > 1000: assert t >= 1050
assert open(D + "vn_done.txt").read().split() == ["aa", "cc", "bb", "dd"] or set(open(D + "vn_done.txt").read().split()) == {"aa", "bb", "cc", "dd"}
assert open(D + "vn_deferred.jsonl").read().strip() == ""
print("ok driver schedule:", calls)

# 10 driver restart keeps the persisted queue; not due yet -> nothing run, waits; cool-down -> no child at all
open(D + "vn_done.txt", "w").write("aa\n")
DR.save_deferred({"bb": {"not_before": 5000.0, "status": "deferred", "attempts": 1, "items": [{"slug": "bb", "item": "7", "url": "u7", "not_before": 5000.0}]}}, D)
q = DR.load_deferred(D); assert q["bb"]["not_before"] == 5000.0 and q["bb"]["items"][0]["item"] == "7"
calls.clear(); clock[0] = 1000.0; script["bb"] = [{"status": "complete", "docs": 1, "deferred": []}]
res = DR.drive(["aa", "bb"], d=D, runner=runner, wb_available=lambda: True, host_cooldown=lambda: 0.0, sleep=sleep, clock=lambda: clock[0], max_loops=100)
assert res == "finished" and calls and calls[0][1] >= 5000.0, calls
calls.clear(); open(D + "vn_done.txt", "w").write("aa\n"); script["bb"] = [{"status": "complete", "docs": 1, "deferred": []}]
res = DR.drive(["aa", "bb"], d=D, runner=runner, wb_available=lambda: False, host_cooldown=lambda: 0.0, sleep=sleep, clock=lambda: clock[0], max_loops=3)
assert res == "max_loops" and not calls                             # breaker open: wait in place, no child
res = DR.drive(["aa", "bb"], d=D, runner=runner, wb_available=lambda: True, host_cooldown=lambda: 400.0, sleep=sleep, clock=lambda: clock[0], max_loops=3)
assert res == "max_loops" and not calls                             # host cooling: no child
# 11 child crash x MAX -> parked, never done
calls.clear(); open(D + "vn_done.txt", "w").write("aa\n"); open(D + "vn_deferred.jsonl", "w").close(); script["bb"] = [None] * 10
res = DR.drive(["aa", "bb"], d=D, runner=runner, wb_available=lambda: True, host_cooldown=lambda: 0.0, sleep=sleep, clock=lambda: clock[0], max_loops=100)
assert res == "finished" and len(calls) == DR.MAX_CHILD_ERRORS and "bb" not in open(D + "vn_done.txt").read()
assert json.loads(open(D + "vn_deferred.jsonl").readline())["status"] == "parked"
print("ok driver restart/persist, breaker wait, cool-down wait, crash->parked")

# ---------------- 12:10 PT API follow-up -------------------------------------------------------------------------
import requests
from archive.core import CaptureList
def clear_cool():
    p_ = rl.RATE_DIR / "host_cooldown.json"
    if p_.exists():
        d_ = json.loads(p_.read_text())
        for h in d_.values(): h["not_before"] = 0; h["consec"] = 0
        p_.write_text(json.dumps(d_))
# 12 a listing flagged truncated/deferred (CaptureList) -> province deferred, never complete/empty
class FakeFXList(FakeFX):
    def wb_captures(self, *a, **k):
        cl = CaptureList(self.caps[:2]); return cl.flag(ArchiveDeferred("cc idx 503", host="index.commoncrawl.org", family="cc_index", not_before=time.time() + 90))
recs, st = pp(FakeFXList(5)); assert st["status"] == "deferred" and recs == [] and st.get("listing_truncated") and 80 < st["not_before"] - time.time() <= 91, st
cl = CaptureList([]); cl.truncated = True
class FakeFXList2(FakeFX):
    def wb_captures(self, *a, **k): return cl
recs, st = pp(FakeFXList2(0)); assert st["status"] == "deferred" and st["not_before"] > time.time() + 200, st   # truncated w/o deferral
recs, st = pp(FakeFX(0)); assert st["status"] == "complete" and recs == []                                    # genuine empty stays empty
print("ok truncated/deferred CaptureList -> province deferred")

# 13 timeouts (new: 1 retry, then ArchiveTransient; still breaker failures) -> never complete / done
class TSess(Sess):
    def get(self, url, **k):
        self.calls.append(url); code, hdr, body = self.plan.pop(0)
        if code == "timeout": raise requests.ReadTimeout("read timed out (fake)")
        r = requests.Response(); r.status_code = code; r.headers.update(hdr); r.raw = Raw(body); r.url = url; return r
clear_cool()
fx = ArchiveFetcher(cache_dir=str(TMP / "cache2"), use_cc=False, lane="sasia_ru_test")
assert fx.timeout_retries == 1
fx.s = TSess([("timeout", {}, b""), ("timeout", {}, b"")])          # CDX: timeout, retry timeout -> ArchiveTransient
t1 = time.time(); recs, st = pp(fx)
assert st["status"] in ("transient", "breaker") and len(fx.s.calls) == 2 and st["deferred"][0]["item"] == "__cdx__", (st, fx.s.calls)
q = {}; assert DR.apply_result("phuyen", 0, st, q, time.time()) in ("requeued", "breaker") and "phuyen" in q
print("ok CDX timeout x2 ->", st["status"], f"({time.time()-t1:.1f}s)")
if hasattr(rl, "breaker_reset"): rl.breaker_reset()
clear_cool()
fx.s = TSess([(200, {}, cdx), ("timeout", {}, b""), ("timeout", {}, b""), (200, {"Content-Type": "text/html"}, BODY)])
recs, st = pp(fx)
assert st["status"] in ("transient", "breaker") and len(recs) <= 1 and [d["item"] for d in st["deferred"]] == ["2"], (st, fx.s.calls)
res = DR.apply_result("phuyen", 0, st, q, time.time()); assert res in ("requeued", "breaker") and q["phuyen"]["status"] != "complete"
print("ok item timeout x2 ->", st["status"], "recs", len(recs), "calls", len(fx.s.calls))
if hasattr(rl, "breaker_reset"): rl.breaker_reset()
clear_cool()

# 14 driver: cdx_error no longer 'done'; parked after MAX
q = {}
for i in range(DR.MAX_CHILD_ERRORS):
    r_ = DR.apply_result("zz", 0, {"status": "cdx_error", "docs": 0, "deferred": [], "error": "wayback cdx non-json"}, q, 1000.0)
    assert r_ != "done"
assert r_ == "parked" and q["zz"]["status"] == "parked"
print("ok cdx_error -> requeued then parked, never done")

# 15 pk_sd_retry.archive_try against the new fetch_newest contract
import importlib.util
spec = importlib.util.spec_from_file_location("pk_sd_retry", (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/sasia_ru/pk_sd_retry.py"))
PK = importlib.util.module_from_spec(spec); spec.loader.exec_module(PK)    # __main__ guard: no work on import
assert not hasattr(PK, "F")
PDF = b"%PDF-1.4 fake " + b"x" * 500
class FN:
    def __init__(self, ret=None, exc=None, wbdef=0): self.ret, self.exc, self.last_wb_deferred = ret, exc, wbdef
    def fetch_newest(self, url, validator=None):
        if self.exc: raise self.exc
        if self.ret is not None and validator and not validator(self.ret): return None
        return self.ret
class DD: body = PDF
class DH: body = b"<html>not a pdf</html>"
def at(F_, name):
    p_ = str(TMP / name); tr = []; nb = PK.archive_try(F_, "https://sindh.example/x.pdf", p_, tr); return nb, tr, os.path.exists(p_)
nb, tr, ok = at(FN(ret=DD()), "a.pdf"); assert nb is None and tr == ["archive:ok"] and ok
nb, tr, ok = at(FN(ret=None), "b.pdf"); assert nb is None and tr == ["archive:nocapture"] and not ok           # genuine miss
nb, tr, ok = at(FN(ret=DH()), "c.pdf"); assert nb is None and tr == ["archive:nocapture"] and not ok           # HTML rejected
nb, tr, ok = at(FN(exc=ArchiveDeferred("x", family="cc_index", host="index.commoncrawl.org", not_before=time.time() + 77)), "d.pdf")
assert 70 < nb - time.time() <= 77 and tr == ["archive:deferred:cc_index"] and not ok
nb, tr, ok = at(FN(exc=ArchiveTransient("wayback giving up after 2 timeout/network failure(s)")), "e.pdf"); assert nb and tr == ["archive:transient"]
nb, tr, ok = at(FN(ret=None, wbdef=3), "f.pdf"); assert nb and tr == ["archive:breaker_skipped"]
# real fetcher: CC index 503 (listing deferred) + Wayback CDX empty -> fetch_newest raises -> archive:deferred
clear_cool()
fx = ArchiveFetcher(cache_dir=str(TMP / "cache3"), use_cc=True, cc_crawls=["CC-MAIN-2099-01"], lane="sasia_ru_test")
fx.s = TSess([(503, {}, b"busy"), (200, {}, b"[]")])
nb, tr, ok = at(fx, "g.pdf")
assert nb and tr[0].startswith("archive:deferred") and "cc_index" in tr[0] and not ok and len(fx.s.calls) == 2, (tr, fx.s.calls)
cl = fx.cc_captures("https://sindh.example/x.pdf")       # host cooling: flagged listing, no request, no exception
assert isinstance(cl, CaptureList) and cl.truncated and cl.deferred and cl.deferral.not_before > time.time() and len(fx.s.calls) == 2
print("ok pk_sd_retry.archive_try (ok/miss/html/deferred/transient/breaker; real CC 503 -> deferred)", tr)

print("ALL OK; temp dir", TMP)
