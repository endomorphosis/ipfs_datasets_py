"""DE archive pass: Wayback breaker deferral + ArchiveDeferred (429/5xx cool-down) requeue. No network, temp dirs."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import importlib.util, json, logging, sys, tempfile, threading, time
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("dap", HERE / "de_archive_pass.py")
dap = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(dap)
from archive.core import ArchivedDoc, CaptureList  # noqa: E402

PDF_A = "https://x.de/satzung.pdf"
PDF_B = "https://x.de/gebuehrensatzung.pdf"


class Cap:
    def __init__(self, u, src="wayback"):
        self.original_url, self.source, self.status, self.timestamp = u, src, 200, "20240101000000"


def html_doc(u):
    body = ("<html><head><title>Satzung</title></head><body><main><h1>Satzung</h1><p>"
            + "Paragraph 1 Geltungsbereich dieser Satzung der Gemeinde X. " * 6 + "</p></main></body></html>").encode()
    return ArchivedDoc(original_url=u, archive_source="wayback", archive_crawl_id="wayback",
                       archive_timestamp="2024-01-01T00:00:00Z", archive_url=f"https://web.archive.org/web/20240101000000id_/{u}",
                       http_status=200, content_type="text/html", body=body, content_complete=True, possibly_stale=False)


def deferred_exc(nb, family="wayback", reason="throttled"):
    return dap.ArchiveDeferred(f"{family} {reason}: deferred", url=PDF_A, host="web.archive.org" if family == "wayback"
                               else "index.commoncrawl.org", family=family, status=429 if reason == "throttled" else None,
                               retry_after=None, not_before=nb, lane="web", reason=reason)


class FakeFx:
    """Mimics the 12:10 PT fetcher. deferred: breaker-style ArchiveTransient. swallow_urls: fetch_best RAISES a
    (merged) ArchiveDeferred for these (nothing usable + throttled). cc_truncated_nb / exact_truncated_nb: cc_captures /
    list_captures return a CaptureList flagged .truncated."""
    def __init__(self, deferred=False, throttle_listing_nb=None, swallow_urls=(), ok_urls=None, cc_truncated_nb=None,
                 exact_truncated_nb=None, defer_family="wayback"):
        self.deferred = deferred; self.last_wb_deferred = 0; self.stats = {}
        self.throttle_listing_nb = throttle_listing_nb
        self.swallow_urls = set(swallow_urls)
        self.ok_urls = ok_urls            # None: everything misses
        self.cc_truncated_nb = cc_truncated_nb
        self.exact_truncated_nb = exact_truncated_nb
        self.defer_family = defer_family
        self.nb = time.time() + 300
        self.calls = []
    def cc_captures(self, prefix, *a, **k):
        self.calls.append(("cc_captures", prefix))
        out = CaptureList()
        if self.cc_truncated_nb:
            out.flag(deferred_exc(self.cc_truncated_nb, family="cc_index"))
        return out
    def wb_captures(self, prefix, *a, **k):
        self.calls.append(("wb_captures", prefix))
        if self.throttle_listing_nb:
            self.stats["wayback_deferred"] = self.stats.get("wayback_deferred", 0) + 1
            raise deferred_exc(self.throttle_listing_nb)
        if self.deferred:
            raise dap.ArchiveTransient("wayback breaker open (box-wide); skipped")
        return [Cap(PDF_A), Cap(PDF_B)]
    def list_captures(self, u, m):
        out = CaptureList([Cap(u)] if not self.exact_truncated_nb else [])
        if self.exact_truncated_nb:
            out.flag(deferred_exc(self.exact_truncated_nb))
        return out
    def fetch_best(self, caps, **k):
        u = caps[0].original_url
        self.calls.append(("fetch_best", u))
        if u in self.swallow_urls:      # nothing usable and a source was throttled -> raises (new fetcher)
            self.last_wb_deferred = 1 if self.defer_family == "wayback" else 0
            raise deferred_exc(self.nb, family=self.defer_family)
        self.last_wb_deferred = len(caps) if self.deferred else 0
        if self.ok_urls is not None and u in self.ok_urls:
            return html_doc(u)
        return None
    def fetch_newest(self, u, **k): return self.fetch_best([Cap(u)])


def setdirs(tmp):
    dap.QUAR = Path(tmp) / "q"; dap.STAGE = Path(tmp) / "s"; dap.WORK = Path(tmp) / "w"; dap.TMP = dap.WORK / "_tmp"
    dap.CONT_F = dap.WORK / "pending_docs.jsonl"; dap.WORK.mkdir(parents=True, exist_ok=True)


def mk(fx, tmp, cands=None, stop=None, cont=None):
    setdirs(tmp)
    t = {"place_id": "wd:Q1", "name": "X", "homepage": "https://x.de/"}
    r = {"place_id": "wd:Q1", "status": "docs_robots_disallowed", "section_pages": []}
    pa = dap.PlaceArchiver(fx, t, r, Path(tmp) / "c.sqlite", stop or threading.Event(), cont=cont)
    cands = cands or {PDF_A: ("Satzung", None)}
    pa.collect = lambda: dict(cands)
    return pa


def staged_lines(tmp):
    return [json.loads(l) for f in sorted((Path(tmp) / "s" / "DE").glob("*.jsonl")) for l in f.open()]


def _wb(cool=0.0, avail=True):
    dap.ratelimit.wayback_available = lambda: avail
    dap.deferral.host_cooldown = lambda host: cool
    dap.wb_cooling = lambda: cool


# ---------------------------------------------------------------- breaker (existing behaviour)
def test_defer_when_breaker_open():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(avail=False)
        res = mk(FakeFx(True), tmp).run()
        assert res["status"] == "deferred_wayback" and res["wb_deferred"] >= 1 and res.get("fetch_fail", 0) == 0


def test_real_miss_still_fails():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        res = mk(FakeFx(False), tmp).run()
        assert res["status"] == "no_docs" and res["fetch_fail"] == 1


# ---------------------------------------------------------------- ArchiveDeferred requeue
def test_archive_deferred_requeues_doc_with_not_before():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(cool=0.0)
        nb = time.time() + 120
        pa = mk(FakeFx(throttle_listing_nb=nb), tmp)
        res = pa.run()
        assert res["status"] == "deferred_throttle", res
        assert abs(res["not_before"] - nb) < 0.01                 # e.not_before is honoured
        assert res["pending_docs"] == 1 and pa.pending[0][0] == PDF_A and pa.pending[0][3] == "throttle"
        assert res["no_capture"] == 0 and res["fetch_fail"] == 0 and res["docs"] == 0   # not a failure
        assert pa.collected                                        # requeue only the doc, not discovery


def test_not_before_floor_when_retry_after_zero():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        res = mk(FakeFx(throttle_listing_nb=time.time() - 10), tmp).run()
        assert res["status"] == "deferred_throttle" and res["not_before"] >= time.time() + dap.DEFER_MIN_S - 1


def test_fetch_best_raises_deferred_is_requeued_not_failed():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(cool=300.0)
        fx = FakeFx(swallow_urls={PDF_A})
        pa = mk(fx, tmp)
        res = pa.run()
        assert res["status"] == "deferred_throttle", res
        assert res["fetch_fail"] == 0 and res["no_capture"] == 0 and res["pending_docs"] == 1
        assert abs(res["not_before"] - fx.nb) < 0.01               # e.not_before


def test_fetch_best_cc_only_deferral_requeued_for_its_not_before():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(cool=0.0)                                              # Wayback fine, CC index cooling
        fx = FakeFx(swallow_urls={PDF_A}, ok_urls={PDF_B}, defer_family="cc_index")
        pa = mk(fx, tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "deferred_throttle" and res["pending_docs"] == 1 and res["docs"] == 1, res
        assert abs(res["not_before"] - fx.nb) < 0.01 and pa.pending[0][0] == PDF_A
        assert res["throttle_cc_index"] == 1
        # Wayback not cooling: the CC deferral did not stop the rest of the place
        assert ("fetch_best", PDF_B) in fx.calls


def test_fetch_best_none_is_genuine_miss():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        pa = mk(FakeFx(), tmp)
        res = pa.run()
        assert res["status"] == "no_docs" and res["fetch_fail"] == 1 and not pa.pending and pa.throttled == 0


def test_truncated_cc_listing_requeues_doc_not_no_capture():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        nb = time.time() + 200
        fx = FakeFx(cc_truncated_nb=nb)
        fx.wb_captures = lambda *a, **k: CaptureList()            # Wayback listing complete but empty
        pa = mk(fx, tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "deferred_throttle" and res["no_capture"] == 0, res
        assert res["pending_docs"] == 2 and abs(res["not_before"] - nb) < 0.01
        assert ("x.de/", False) not in pa.listings                 # incomplete listing not cached
        assert [c for c in fx.calls if c[0] == "cc_captures"] == [("cc_captures", "x.de/")]   # listed once per segment
        # next segment, CC recovered and the listing has the docs
        fx.cc_truncated_nb = None
        fx.ok_urls = {PDF_A, PDF_B}
        fx.wb_captures = lambda *a, **k: CaptureList([Cap(PDF_A), Cap(PDF_B)])
        res2 = pa.run()
        assert res2["status"] == "recovered" and res2["docs"] == 2 and res2["no_capture"] == 0, res2


def test_truncated_exact_lookup_requeues_doc():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        nb = time.time() + 75
        u = "https://daten.verwaltungsportal.de/dateien/satzung.pdf"      # shared host -> exact lookup
        pa = mk(FakeFx(exact_truncated_nb=nb), tmp, cands={u: ("Satzung", None)})
        res = pa.run()
        assert res["status"] == "deferred_throttle" and res["no_capture"] == 0 and res["pending_docs"] == 1, res
        assert pa.lookups[0] == 0                                  # lookup budget given back for the retry


def test_truncated_listing_in_discovery_requeues_place_not_no_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        setdirs(tmp)
        fx = FakeFx(cc_truncated_nb=time.time() + 120)
        fx.wb_captures = lambda *a, **k: CaptureList()
        fx.fetch_newest = lambda u, **k: None
        t = {"place_id": "wd:Q9", "name": "Y", "homepage": "https://y.de/"}
        r = {"place_id": "wd:Q9", "status": "docs_robots_disallowed", "section_pages": []}
        pa = dap.PlaceArchiver(fx, t, r, Path(tmp) / "c.sqlite", threading.Event())
        res = pa.run()                                             # real collect(): html listing of y.de/ truncated
        assert res["status"] == "deferred_throttle", res          # not no_candidates
        assert not pa.collected and not pa.files


def test_doc_level_requeue_then_resume_stages_each_doc_once():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(cool=0.0)
        fx = FakeFx(swallow_urls={PDF_B}, ok_urls={PDF_A, PDF_B})
        pa = mk(fx, tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "deferred_throttle" and res["docs"] == 1 and res["pending_docs"] == 1, res
        assert [p[0] for p in pa.pending] == [PDF_B] and len(pa.files) == 1
        assert len(staged_lines(tmp)) == 1
        # survives a restart: state -> new archiver resumes only the pending doc
        cont = json.loads(json.dumps(pa.state()))
        fx2 = FakeFx(ok_urls={PDF_A, PDF_B})
        pa2 = mk(fx2, tmp, cont=cont)
        pa2.collect = lambda: (_ for _ in ()).throw(AssertionError("collect must not rerun"))
        res2 = pa2.run()
        assert res2["status"] == "recovered" and res2["docs"] == 2 and res2["segments"] == 2, res2
        assert [c for c in fx2.calls if c[0] == "fetch_best"] == [("fetch_best", PDF_B)]
        assert len(res2["files"]) == 2
        lines = staged_lines(tmp)
        assert len(lines) == 2 and len({l["doc_id"] for l in lines}) == 2


def test_cooling_bails_out_of_rest_of_place():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(cool=600.0)
        fx = FakeFx(swallow_urls={PDF_A, PDF_B})
        pa = mk(fx, tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "deferred_throttle" and res["pending_docs"] == 2
        assert len([c for c in fx.calls if c[0] == "fetch_best"]) == 1   # second doc not even tried


def test_collect_throttle_requeues_whole_place():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        fx = FakeFx()
        pa = mk(fx, tmp)

        def collect():
            pa._note_throttle(deferred_exc(time.time() + 90))
            return {PDF_A: ("Satzung", None)}
        pa.collect = collect
        res = pa.run()
        assert res["status"] == "deferred_throttle" and not pa.collected and not pa.files
        assert fx.calls == []                                       # no doc work started


def test_deferral_classification():
    assert dap._is_deferral(deferred_exc(time.time() + 60, family="cc_index"))
    assert dap._is_deferral(deferred_exc(time.time() + 60))
    assert not dap._is_deferral(dap.ArchiveTransient("wayback breaker open"))
    assert issubclass(dap.ArchiveDeferred, dap.ArchiveTransient)
    assert dap._truncated(CaptureList().flag(deferred_exc(1))) and not dap._truncated(CaptureList()) and not dap._truncated([])


def test_stop_keeps_remaining_docs_pending():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        ev = threading.Event(); ev.set()
        pa = mk(FakeFx(ok_urls={PDF_A}), tmp, stop=ev)
        res = pa.run()
        assert res["status"] == "interrupted" and [p[3] for p in pa.pending] == ["stop"]


# ---------------------------------------------------------------- scheduler / logging
def R(i): return {"place_id": f"wd:Q{i}", "status": "docs_robots_disallowed"}


def test_scheduler_waits_for_earliest_not_before_with_cap():
    _wb(cool=0.0)
    s = dap.Scheduler([], {})
    s.busy = 2
    s.requeue(R(1), time.time() + 40, "throttle"); s.requeue(R(2), time.time() + 500, "throttle")
    item, wait = s.next()
    assert item is None and 38 <= wait <= 40.5                    # earliest not_before, not a busy loop
    s2 = dap.Scheduler([], {}); s2.busy = 1
    s2.requeue(R(3), time.time() + 5000, "throttle")
    assert s2.next() == (None, dap.IDLE_WAIT_CAP_S)               # capped
    s3 = dap.Scheduler([], {}); s3.busy = 1
    s3.requeue(R(4), time.time() - 1, "throttle")
    item, wait = s3.next()
    assert item[0]["place_id"] == "wd:Q4" and wait is None
    assert s3.next() == (None, dap.IDLE_WAIT_CAP_S)               # busy worker may still requeue: wait, not exit
    s3.done_one()
    assert s3.next() == (None, None)                              # nothing left: finished


def test_scheduler_gates_fresh_and_due_items_while_wayback_cooling():
    _wb(cool=120.0)
    s = dap.Scheduler([R(1)], {}); s.busy = 1
    s.requeue(R(2), time.time() - 1, "throttle")
    item, wait = s.next()
    assert item is None and wait == min(dap.IDLE_WAIT_CAP_S, 120.0)   # overdue item still waits for the cool-down
    _wb(cool=0.0)
    item, _ = s.next(); assert item[0]["place_id"] == "wd:Q2"      # due deferred item before fresh work
    item, _ = s.next(); assert item[0]["place_id"] == "wd:Q1"


def test_scheduler_breaker_items_retry_when_breaker_closes():
    _wb(cool=0.0, avail=False)
    s = dap.Scheduler([], {}); s.busy = 1
    s.requeue(R(1), time.time() + dap.DEFER_RETRY_S, "breaker")
    assert s.next()[0] is None
    _wb(cool=0.0, avail=True)
    assert s.next()[0][0]["place_id"] == "wd:Q1"


def test_defer_log_once_per_place_per_cooldown():
    d = dap.DeferLog()
    nb = time.time() + 60
    assert d.should_log("p1", nb) and not d.should_log("p1", nb) and d.should_log("p2", nb)
    d.until["p1"] = time.time() - 1                                # cool-down over -> next deferral logs again
    assert d.should_log("p1", time.time() + 120) and d.suppressed == 1


def test_archive_log_limiter():
    f = dap.ArchiveLogLimiter()
    recs = [logging.LogRecord("world_law.archive", logging.WARNING, "x", 1, "CC %s %s failed: %s", ("a", "b", "c"), None)
            for _ in range(50)]
    assert sum(f.filter(r) for r in recs) == f.PER_WINDOW


def test_load_continuations_last_wins_and_cleared(tmp_path=None):
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp)
        with dap.CONT_F.open("w") as fh:
            fh.write(json.dumps({"place_id": "a", "pending": [[1]]}) + "\n")
            fh.write(json.dumps({"place_id": "a", "pending": [[2]]}) + "\n")
            fh.write(json.dumps({"place_id": "b", "pending": [[3]]}) + "\n")
            fh.write(json.dumps({"place_id": "b", "cleared": True}) + "\n")
            fh.write(json.dumps({"place_id": "c", "pending": [[4]]}) + "\n")
        c = dap.load_continuations({"c"})
        assert list(c) == ["a"] and c["a"]["pending"] == [[2]]


class OnceThrottledFx(FakeFx):
    """PDF_B is throttled (swallowed ArchiveDeferred) on its first fetch, served afterwards."""
    hits = {}
    def fetch_best(self, caps, **k):
        u = caps[0].original_url
        n = OnceThrottledFx.hits[u] = OnceThrottledFx.hits.get(u, 0) + 1
        self.calls.append(("fetch_best", u))
        if u == PDF_B and n == 1:
            self.last_wb_deferred = 1
            raise deferred_exc(time.time() + 0.3)
        self.last_wb_deferred = 0
        return html_doc(u)


def test_main_end_to_end_requeue_no_done_until_complete():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp)
        _wb(cool=0.0)
        saved = (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
                 dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker)
        try:
            dap.S = Path(tmp); dap.LOGS = Path(tmp) / "logs"; dap.DEFER_MIN_S = 0.2
            (Path(tmp) / "_state").mkdir()
            rs = {f"wd:Q{i}": {"place_id": f"wd:Q{i}", "status": "docs_robots_disallowed", "section_pages": []} for i in (1, 2)}
            dap.load_results = lambda: rs
            dap.C.load_targets = lambda: [{"place_id": k, "name": k} for k in rs]
            OnceThrottledFx.hits = {}
            dap.ArchiveFetcher = lambda **k: OnceThrottledFx(ok_urls={PDF_A, PDF_B})
            dap.PlaceArchiver.collect = lambda self: ({PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)}
                                                      if self.t["place_id"] == "wd:Q1" else {PDF_A: ("Satzung", None)})
            sys.argv = ["x", "--workers", "2", "--log", str(Path(tmp) / "a.log"), "--no-cover-check"]
            t0 = time.time()
            dap.main()
            assert time.time() - t0 < 20
            done = [json.loads(l) for l in (dap.WORK / "done.jsonl").open()]
            st = {d["place_id"]: d for d in done}
            assert len(done) == 2 and st["wd:Q1"]["status"] == "recovered" and st["wd:Q1"]["docs"] == 2, done
            assert st["wd:Q1"]["segments"] == 2 and st["wd:Q1"]["fetch_fail"] == 0
            assert all(d["status"] != "deferred_throttle" for d in done)
            prog = json.loads((dap.WORK / "_progress.json").read_text())
            assert prog["deferred_throttle_events"] == 1 and prog["finished"] and prog["deferred_pending"] == 0
            logtxt = (Path(tmp) / "a.log").read_text()
            assert logtxt.count("DEFERRED") == 1, logtxt
            ids = [(l["place_id"], l["doc_id"]) for l in staged_lines(tmp)]
            assert len(ids) == len(set(ids)) == 3
            assert (dap.WORK / "deferred_throttle.tsv").read_text().count("wd:Q1") == 1
        finally:
            if dap.LOG_FH:
                dap.LOG_FH.close()
            (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
             dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker) = saved



# ---------------------------------------------------------------- fetcher round 3 (12:25 PT): completeness signals
class R3Fx(FakeFx):
    """fetch_best raises `exc` (and leaves a stale last_wb_deferred, like the real fetcher may) or returns `doc`."""
    def __init__(self, exc=None, doc=None, stale_wb=0, **k):
        super().__init__(**k); self.exc, self.doc, self.stale_wb = exc, doc, stale_wb
    def fetch_best(self, caps, **k):
        self.calls.append(("fetch_best", caps[0].original_url))
        self.last_wb_deferred = self.stale_wb
        if self.exc is not None:
            raise self.exc
        return self.doc


def test_r3_breaker_raise_requeued_once_as_breaker_at_next_probe():
    with tempfile.TemporaryDirectory() as tmp:
        _wb(avail=False)
        nb = time.time() + 1700                                   # the breaker's next probe
        pa = mk(R3Fx(exc=deferred_exc(nb, reason="breaker_open"), stale_wb=3), tmp)
        res = pa.run()
        assert res["status"] == "deferred_wayback", res
        assert pa.pending == [[PDF_A, "Satzung", None, "breaker"]]   # exactly one entry: no double handling
        assert res["fetch_fail"] == 0 and res["no_capture"] == 0 and res["wb_deferred_docs"] == 1
        assert abs(res["not_before"] - nb) < 0.01


def test_r3_timeout_raise_is_requeued_not_breaker_path():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        nb = time.time() + 60
        pa = mk(R3Fx(exc=deferred_exc(nb, reason="timeout"), stale_wb=2), tmp)
        res = pa.run()
        assert res["status"] == "deferred_throttle" and pa.pending == [[PDF_A, "Satzung", None, "throttle"]], res
        assert res["fetch_fail"] == 0 and "wb_deferred_docs" not in res and pa.wb_deferred == 0
        assert res["defer_reason_timeout"] == 1 and abs(res["not_before"] - nb) < 0.01


def test_r3_none_is_genuine_miss_even_with_stale_last_wb_deferred():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        pa = mk(R3Fx(doc=None, stale_wb=5), tmp)
        res = pa.run()
        assert res["status"] == "no_docs" and res["fetch_fail"] == 1 and not pa.pending, res


def test_r3_permanent_truncation_is_accepted_not_requeued():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        fx = R3Fx(doc=None)
        fx.cc_captures = lambda *a, **k: CaptureList().mark("crawl_failed", "CC-MAIN-x 404")   # no .deferral
        fx.wb_captures = lambda *a, **k: CaptureList()
        pa = mk(fx, tmp)
        res = pa.run()
        assert res["status"] == "no_capture" and res["no_capture"] == 1 and not pa.pending, res
        assert ("x.de/", False) in pa.listings and res["listing_truncated_permanent"] == 1


def test_r3_cc_only_deferrals_accepted_after_max_rounds_no_loop():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        fx = R3Fx(doc=None)
        fx.cc_captures = lambda *a, **k: CaptureList().flag(deferred_exc(time.time() + 60, family="cc_index", reason="busy"))
        fx.wb_captures = lambda *a, **k: CaptureList()
        pa = mk(fx, tmp)
        for i in range(dap.MAX_CC_DEFER_ROUNDS):
            res = pa.run()
            assert res["status"] == "deferred_throttle" and res["cc_rounds"] == i + 1, (i, res)
        res = pa.run()                                             # accepted: finishes instead of looping
        assert res["status"] == "no_capture" and not pa.pending, res
        inc = [json.loads(l) for l in (dap.WORK / "incomplete_docs.jsonl").open()]
        assert [r["kind"] for r in inc] == ["listing_partial_cc"] and inc[0]["families"] == ["cc_index"]


def test_r3_wayback_deferral_never_accepted_by_cc_rule():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        pa = mk(R3Fx(exc=deferred_exc(time.time() + 60)), tmp)
        pa.cc_rounds = 99
        assert pa.run()["status"] == "deferred_throttle" and pa.pending


def test_r3_incomplete_doc_is_staged_and_listed_once():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        d = html_doc(PDF_A)
        d.incomplete = True
        d.deferral = deferred_exc(time.time() + 60, family="cc_index", reason="timeout")
        pa = mk(R3Fx(doc=d), tmp)
        res = pa.run()
        assert res["status"] == "recovered" and res["docs"] == 1 and res["incomplete_docs"] == 1 and not pa.pending, res
        assert len(staged_lines(tmp)) == 1
        inc = [json.loads(l) for l in (dap.WORK / "incomplete_docs.jsonl").open()]
        assert len(inc) == 1 and inc[0]["kind"] == "doc" and inc[0]["url"] == PDF_A and inc[0]["reasons"] == ["timeout"]
        assert inc[0]["doc_id"] == staged_lines(tmp)[0]["doc_id"]
        d2 = html_doc(PDF_A)                                       # complete doc: not listed
        pa2 = mk(R3Fx(doc=d2), tmp)
        pa2.t = dict(pa2.t, place_id="wd:Q2"); pa2.r = dict(pa2.r, place_id="wd:Q2")
        assert pa2.run()["status"] == "recovered"
        assert len((dap.WORK / "incomplete_docs.jsonl").read_text().splitlines()) == 1


def test_r3_idle_log_only_on_state_change():
    k = dap.idle_state_key
    assert k(0, 1376, 0.0, "open") == k(0, 1376, 0.0, "open")      # same state every minute: no new line
    assert k(0, 1376, 0.0, "open") != k(0, 1376, 0.0, "ok")
    assert k(0, 1376, 0.0, "open") != k(1, 1376, 0.0, "open")
    assert k(0, 5, 30.0, "ok") == k(0, 5, 12.0, "ok") != k(0, 5, 0.0, "ok")


class R3MainFx(FakeFx):
    """wd:Q1 -> x.de doc OK. wd:Q3 -> z.de: CC listing always deferred (busy), Wayback listing empty."""
    def cc_captures(self, prefix, *a, **k):
        if prefix.startswith("z.de"):
            return CaptureList().flag(deferred_exc(time.time() + 0.1, family="cc_index", reason="busy"))
        return CaptureList()
    def wb_captures(self, prefix, *a, **k):
        return CaptureList([Cap(PDF_A)]) if prefix.startswith("x.de") else CaptureList()
    def fetch_best(self, caps, **k):
        return html_doc(caps[0].original_url)


def test_r3_main_cc_rounds_survive_place_requeue_and_idle_log_quiet():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp)
        _wb(cool=0.0)
        saved = (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
                 dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker)
        try:
            dap.S = Path(tmp); dap.LOGS = Path(tmp) / "logs"; dap.DEFER_MIN_S = 0.2
            (Path(tmp) / "_state").mkdir()
            rs = {f"wd:Q{i}": {"place_id": f"wd:Q{i}", "status": "docs_robots_disallowed", "section_pages": []} for i in (1, 3)}
            dap.load_results = lambda: rs
            dap.C.load_targets = lambda: [{"place_id": k, "name": k} for k in rs]
            dap.ArchiveFetcher = lambda **k: R3MainFx()
            dap.PlaceArchiver.collect = lambda self: ({PDF_A: ("Satzung", None)} if self.t["place_id"] == "wd:Q1"
                                                      else {"https://z.de/satzung.pdf": ("Satzung", None)})
            sys.argv = ["x", "--workers", "2", "--log", str(Path(tmp) / "a.log"), "--no-cover-check"]
            t0 = time.time()
            dap.main()
            assert time.time() - t0 < 30
            st = {d["place_id"]: d for d in map(json.loads, (dap.WORK / "done.jsonl").open())}
            assert st["wd:Q1"]["status"] == "recovered" and st["wd:Q3"]["status"] == "no_capture", st
            assert st["wd:Q3"]["segments"] == dap.MAX_CC_DEFER_ROUNDS + 1
            logtxt = (Path(tmp) / "a.log").read_text()
            assert logtxt.count("DEFERRED") <= dap.MAX_CC_DEFER_ROUNDS
            idle_lines = [l for l in logtxt.splitlines() if " idle: " in l]
            assert len(idle_lines) <= 2 * dap.MAX_CC_DEFER_ROUNDS + 2, idle_lines   # state changes only
        finally:
            if dap.LOG_FH:
                dap.LOG_FH.close()
            (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
             dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker) = saved



# ---------------------------------------------------------------- v0.6: covered URLs, shared Amt/VG docs, round 4/5
class FakeCover:
    def __init__(self, covered=None, boom=False):
        self.map = covered or {}; self.boom = boom; self.stats = dap.collections.Counter(); self.active = True; self.err = None
    def covered(self, url):
        if self.boom:
            self.stats["cover_check_err"] += 1
            return None                     # CoverChecker fails open the same way
        return self.map.get(url)
    def close(self): pass


class with_globals:
    def __init__(self, cover=None, amt=None):
        self.cover, self.amt = cover, amt
    def __enter__(self):
        self.saved = (dap.COVER, dap.AMT)
        if self.cover is not None: dap.COVER = self.cover
        if self.amt is not None: dap.AMT = self.amt
    def __exit__(self, *a):
        dap.COVER, dap.AMT = self.saved


def test_v06_covered_url_skipped_before_any_archive_request():
    with tempfile.TemporaryDirectory() as tmp, with_globals(cover=FakeCover({PDF_A: "endomorphosis/ipfs_germany_municipal_laws"})):
        _wb()
        fx = FakeFx(ok_urls={PDF_A})
        pa = mk(fx, tmp)
        res = pa.run()
        assert res["status"] == "covered_elsewhere" and res["skipped_covered"] == 1 and res["docs"] == 0, res
        assert fx.calls == [] and res["covered_by_old_repo"] == 1      # no listing, no fetch
        assert not staged_lines(tmp) if (Path(tmp) / "s" / "DE").exists() else True


def test_v06_partly_covered_place_recovers_rest():
    with tempfile.TemporaryDirectory() as tmp, with_globals(cover=FakeCover({PDF_A: "world_municipal_law:DE/wd_Q9/web-x"})):
        _wb()
        fx = FakeFx(ok_urls={PDF_A, PDF_B})
        pa = mk(fx, tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "recovered" and res["docs"] == 1 and res["skipped_covered"] == 1, res
        assert res["covered_by_published"] == 1 and ("fetch_best", PDF_A) not in fx.calls


def test_v06_covered_plus_real_miss_is_not_covered_elsewhere():
    with tempfile.TemporaryDirectory() as tmp, with_globals(cover=FakeCover({PDF_A: "endomorphosis/x"})):
        _wb()
        pa = mk(FakeFx(), tmp, cands={PDF_A: ("Hauptsatzung", None), PDF_B: ("Gebuehrensatzung", None)})
        res = pa.run()
        assert res["status"] == "no_docs" and res["skipped_covered"] == 1 and res["fetch_fail"] == 1, res


def test_v06_cover_check_fails_open():
    with tempfile.TemporaryDirectory() as tmp, with_globals(cover=FakeCover(boom=True)):
        _wb()
        res = mk(FakeFx(ok_urls={PDF_A}), tmp).run()
        assert res["status"] == "recovered" and res["docs"] == 1 and dap.COVER.stats["cover_check_err"] == 1


def test_v06_real_cover_checker_against_index():
    idx = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/dedup/old_urls.sqlite"))
    if not idx.exists():
        print("  (skip: no index)"); return
    import resource
    r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    c = dap.CoverChecker()
    assert c.active, c.err
    assert c.covered("https://www.ahaus.de/fileadmin/ahaus/Rathaus/Ortsrecht/10.1.1.pdf") == "endomorphosis/ipfs_germany_municipal_laws"
    assert c.covered("http://ahaus.de/fileadmin/ahaus/Rathaus/Ortsrecht/10.1.1.pdf/") is not None   # norm_url keys
    assert c.covered("https://example.invalid/never-published-%d.pdf" % time.time_ns()) is None
    assert c.stats["cover_check_err"] == 0
    c.close()
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - r0 < 64 * 1024     # < 64 MB


VG = "vg-musterland.de"
def amt_targets():
    mk_t = lambda q, n: {"place_id": f"wd:Q{q}", "name": n, "qid": f"Q{q}", "homepage": f"https://www.{VG}/",
                         "source_url": f"https://www.{VG}/", "code_links": [{"url": f"https://www.{VG}/ortsrecht/"}]}
    return [mk_t(1, "Adorf"), mk_t(2, "Bedorf"), mk_t(3, "Cedorf"),
            {"place_id": "wd:Q7", "name": "Solostadt", "homepage": "https://solostadt.de/", "code_links": []}]


def test_v06_amt_classify_uses_member_names():
    a = dap.AmtIndex(amt_targets())
    assert a.shared(VG) and not a.shared("solostadt.de") and not a.shared("daten.verwaltungsportal.de")
    assert a.shared("amt-irgendwo.de")                                          # Amt-style host name
    u = f"https://www.{VG}/ortsrecht/"
    assert a.classify("wd:Q1", u + "hundesteuersatzung_adorf.pdf", "")[0] == "own"
    assert a.classify("wd:Q1", u + "hauptsatzung_bedorf.pdf", "Hauptsatzung Ortsgemeinde Bedorf") == ("other_member", "wd:Q2")
    assert a.classify("wd:Q1", u + "hauptsatzung_vg.pdf", "Hauptsatzung der Verbandsgemeinde") == ("shared", None)
    assert a.classify("wd:Q1", u + "bedorf_vg_umlage.pdf", "Satzung der VG fuer Bedorf")[0] == "shared"   # names the VG
    assert a.classify("wd:Q7", "https://solostadt.de/a.pdf", "") == ("own", None)
    portal = [{"place_id": f"wd:Q{100+i}", "name": f"Ort{i}", "homepage": "https://service-portal.de/"} for i in range(61)]
    assert not dap.AmtIndex(portal).shared("service-portal.de")


def _amt_place(tmp, pid, url, amt):
    t = next(x for x in amt_targets() if x["place_id"] == pid)
    r = {"place_id": pid, "status": "docs_robots_disallowed", "section_pages": []}
    fx = FakeFx(ok_urls={url})
    fx.list_captures = lambda u, m: CaptureList([Cap(u)])
    fx.wb_captures = lambda *a, **k: CaptureList([Cap(url)])
    pa = dap.PlaceArchiver(fx, t, r, Path(tmp) / "c.sqlite", threading.Event())
    pa.collect = lambda: {url: ("Hauptsatzung der Verbandsgemeinde", None)}
    return pa, fx


def test_v06_shared_amt_doc_staged_once_across_members():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp); _wb()
        url = f"https://www.{VG}/ortsrecht/hauptsatzung_vg.pdf"
        a = dap.AmtIndex(amt_targets(), claims_path=dap.WORK / "shared_amt_claims.jsonl")
        with with_globals(cover=FakeCover(), amt=a):
            pa1, fx1 = _amt_place(tmp, "wd:Q1", url, a)
            r1 = pa1.run()
            assert r1["status"] == "recovered" and r1["shared_amt_docs"] == 1, r1
            pa2, fx2 = _amt_place(tmp, "wd:Q2", url, a)
            r2 = pa2.run()
            assert r2["status"] == "covered_elsewhere" and r2["skipped_shared_amt"] == 1 and fx2.calls == [], r2
        lines = staged_lines(tmp)
        assert len(lines) == 1 and lines[0]["place_id"] == "wd:Q1" and lines[0]["shared_amt_site"] == VG
        # claims survive a restart
        a2 = dap.AmtIndex(amt_targets(), claims_path=dap.WORK / "shared_amt_claims.jsonl")
        assert a2.claimed_by(dap.norm_key(url)) == "wd:Q1"


def test_v06_shared_doc_attributed_to_amt_place_when_registry_has_one():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp); _wb()
        url = f"https://www.{VG}/ortsrecht/hauptsatzung_vg.pdf"
        tg = amt_targets() + [{"place_id": "wd:Q50", "name": "Verbandsgemeinde Musterland", "qid": "Q50",
                               "homepage": f"https://www.{VG}/", "source_url": f"https://www.{VG}/", "code_links": []}]
        a = dap.AmtIndex(tg, claims_path=dap.WORK / "shared_amt_claims.jsonl")
        assert a.amt_place[VG] == "wd:Q50"                               # xdedup.is_amt name rule
        with with_globals(cover=FakeCover(), amt=a):
            pa, _ = _amt_place(tmp, "wd:Q3", url, a)
            res = pa.run()
        assert res["status"] == "recovered" and res["amt_attributed_docs"] == 1 and res["amt_files"], res
        lines = staged_lines(tmp)
        assert len(lines) == 1 and lines[0]["place_id"] == "wd:Q50" and lines[0]["found_via_place_id"] == "wd:Q3"
        assert lines[0]["place_name"] == "Verbandsgemeinde Musterland"
        assert all(f.startswith("wd_Q50.") for f in res["amt_files"]) and not res["files"]


def test_v06_other_member_doc_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp); _wb()
        url = f"https://www.{VG}/ortsrecht/hauptsatzung_bedorf.pdf"
        a = dap.AmtIndex(amt_targets())
        with with_globals(cover=FakeCover(), amt=a):
            pa, fx = _amt_place(tmp, "wd:Q1", url, a)
            pa.collect = lambda: {url: ("Hauptsatzung Bedorf", None)}
            res = pa.run()
        assert res["skipped_other_member"] == 1 and res["docs"] == 0 and fx.calls == [], res


def test_v06_typed_listing_errors_round4():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        fx = FakeFx()
        fx.wb_captures = lambda *a, **k: (_ for _ in ()).throw(dap.ArchiveTimeout("wayback giving up: timeout"))
        pa = mk(fx, tmp)
        res = pa.run()
        assert res["status"] == "deferred_throttle" and pa.pending[0][3] == "throttle", res
        assert time.time() + 50 < res["not_before"] < time.time() + 70            # ~60 s, not the 30-min breaker wait
        fx2 = FakeFx()
        fx2.wb_captures = lambda *a, **k: (_ for _ in ()).throw(dap.ArchiveBreakerOpen("wayback breaker open"))
        pa2 = mk(fx2, tmp)
        res2 = pa2.run()
        assert res2["status"] == "deferred_wayback" and pa2.pending[0][3] == "breaker", res2


def test_v06_retryable_vs_permanent_truncation_flags():
    perm = CaptureList().mark("crawl_failed", "permanent: 404")
    assert perm.truncated and perm.complete_except_permanent and not perm.retryable_truncation
    assert not dap._truncated(perm)
    retry = CaptureList().flag(deferred_exc(time.time() + 60))
    assert retry.retryable_truncation and dap._truncated(retry)


def test_v06_unknown_error_gap_accepted_after_max_rounds():
    with tempfile.TemporaryDirectory() as tmp:
        _wb()
        fx = R3Fx(doc=None)
        fx.cc_captures = lambda *a, **k: CaptureList()
        fx.wb_captures = lambda *a, **k: CaptureList()
        fx.list_captures = lambda u, m: CaptureList().flag(deferred_exc(time.time() + 3600, reason="unknown_error"))
        u = "https://daten.verwaltungsportal.de/dateien/satzung.pdf"                # exact lookup
        pa = mk(fx, tmp, cands={u: ("Satzung", None)})
        for i in range(dap.MAX_UNKNOWN_ROUNDS):
            res = pa.run()
            assert res["status"] == "deferred_throttle" and res["unknown_rounds"] == i + 1, (i, res)
        res = pa.run()
        assert res["status"] == "no_capture" and not pa.pending, res


def test_v06_main_counts_skipped_covered_in_progress_and_log():
    with tempfile.TemporaryDirectory() as tmp:
        setdirs(tmp); _wb(cool=0.0)
        saved = (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
                 dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker)
        try:
            dap.S = Path(tmp); dap.LOGS = Path(tmp) / "logs"; (Path(tmp) / "_state").mkdir(); dap.RUN_SKIPS.clear()
            rs = {f"wd:Q{i}": {"place_id": f"wd:Q{i}", "status": "docs_robots_disallowed", "section_pages": []} for i in (1, 2)}
            dap.load_results = lambda: rs
            dap.C.load_targets = lambda: [{"place_id": k, "name": k} for k in rs]
            dap.ArchiveFetcher = lambda **k: FakeFx(ok_urls={PDF_A, PDF_B})
            dap.CoverChecker = lambda enabled=True: FakeCover({PDF_A: "endomorphosis/ipfs_germany_municipal_laws"})
            dap.PlaceArchiver.collect = lambda self: ({PDF_A: ("Satzung", None)} if self.t["place_id"] == "wd:Q1"
                                                      else {PDF_A: ("Satzung", None), PDF_B: ("Gebuehren", None)})
            sys.argv = ["x", "--workers", "2", "--log", str(Path(tmp) / "a.log")]
            dap.main()
            st = {d["place_id"]: d for d in map(json.loads, (dap.WORK / "done.jsonl").open())}
            assert st["wd:Q1"]["status"] == "covered_elsewhere" and st["wd:Q2"]["status"] == "recovered", st
            prog = json.loads((dap.WORK / "_progress.json").read_text())
            assert prog["skips_this_run"]["skipped_covered"] == 2 and prog["agg"]["skipped_covered"] == 2
            assert prog["agg"]["status_covered_elsewhere"] == 1
            logtxt = (Path(tmp) / "a.log").read_text()
            assert "skipped_covered=1" in logtxt and "cover check: on" in logtxt
        finally:
            if dap.LOG_FH:
                dap.LOG_FH.close()
            (dap.S, dap.LOGS, dap.ArchiveFetcher, dap.load_results, dap.C.load_targets, dap.DEFER_MIN_S,
             dap.PlaceArchiver.collect, sys.argv, dap.LOG_FH, dap.COVER, dap.AMT, dap.CoverChecker) = saved


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("PASS", k)
    print("ok")
