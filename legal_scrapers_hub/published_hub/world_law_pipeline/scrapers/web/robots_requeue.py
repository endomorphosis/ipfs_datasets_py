#!/usr/bin/env python3
"""Robots requeue lane (Benjamin, 2026-11-01): live-crawl places that were skipped / partly skipped because of
robots.txt, with IGNORE_ROBOTS=1 (rfc9309 switch). Politeness unchanged: 1 in flight per host, >=2 s between
requests, Crawl-delay honoured up to 10 s (longer = 10 s), same honest User-Agent, no proxies, no logins.
Challenge / 403 / 429 block pages are recorded as blocked and the host is dropped for the rest of the place.
Every non-homepage URL is checked with tools/old_url_check (dedup skip) before it is fetched.

  robots_requeue.py --lane IT|DE|FR|CA|_missing [--workers 2] [--max-places 150]
State (cache, done list, results, progress): staging/web/_requeue/<lane>/. Output: staging/web/<CC>/
<place_key>.<BATCH_KIND>.<UTC>.jsonl, tmp in the lane state dir -> fsync -> validate -> rename (never modified after).
REQUEUE_BATCH_KIND=full makes it a .full batch (replaces the whole place incl. archived docs); default 'robotslive'
(merged by doc_id, newest wins, nothing older dropped)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os
os.environ["IGNORE_ROBOTS"] = "1"
import argparse, datetime as dt, importlib.util, json, re, sys, threading, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web"))
RQ = WEB / "_requeue"
LISTS = RQ / "lists"
MODS = {"IT": "it_bylaw_crawler.py", "DE": "de_ortsrecht_crawler.py", "FR": "fr_actes_crawler.py",
        "CA": "ca_bylaw_crawler.py", "_missing": "missing_urls_crawler.py"}
BATCH_KIND = os.environ.get("REQUEUE_BATCH_KIND", "robotslive")
POLICY = "live_robots_ignored"
NOTE = ("live fetch with robots.txt Disallow ignored per owner policy 2026-11-01 (IGNORE_ROBOTS=1); "
        "polite limits kept: 1 request/host in flight, >=2 s spacing, Crawl-delay honoured up to 10 s")
CHALLENGE = re.compile(rb"cf-chl|challenge-platform|Just a moment\.\.\.|Attention Required! \| Cloudflare|"
                       rb"g-recaptcha|h-captcha|hcaptcha\.com|captcha-delivery|Access Denied</title>|_Incapsula_Resource|"
                       rb"Request unsuccessful\. Incapsula", re.I)

sys.path.insert(0, str(HERE))
import rfc9309  # noqa: E402
assert rfc9309.ignore_robots()
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools"))
from old_url_check import UrlChecker  # noqa: E402


def load_lane(lane):
    sys.argv = [sys.argv[0]]  # modules must not see our flags at import
    spec = importlib.util.spec_from_file_location(f"rq_{lane.strip('_')}", HERE / MODS[lane])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, getattr(mod, "base", mod)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", required=True, choices=list(MODS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-places", type=int, default=150)
    a = ap.parse_args()
    lane = a.lane
    state = RQ / lane
    state.mkdir(parents=True, exist_ok=True)
    ids = [json.loads(l)["place_id"] for l in (LISTS / f"{lane}.jsonl").open()]
    order = {p: i for i, p in enumerate(ids)}
    mod, base = load_lane(lane)

    # ---- targets: only the requeue list (robots-blocked first, as listed)
    orig_lt = (mod.load_targets if lane == "_missing" else base.load_targets)

    def load_targets():
        ts = [t for t in orig_lt() if t["place_id"] in order]
        ts.sort(key=lambda t: order[t["place_id"]])
        return ts
    base.load_targets = load_targets
    if lane == "_missing":
        mod.OUT = state                                   # _Sink tmp dir
        mod.AQ = state / "_state" / "archive_queue.jsonl"  # never touch the _missing archive queue

    # ---- records: tag policy
    orig_rec = base.to_schema_record

    def to_schema_record(d, order_):
        rec = orig_rec(d, order_)
        rec["source_policy"] = POLICY
        rec["source_policy_note"] = NOTE
        rec.pop("robots_disallowed", None); rec.pop("robots_txt_disallowed", None)
        return rec
    base.to_schema_record = to_schema_record

    # ---- fetch: dedup skip, challenge/403 = blocked (host dropped for this place)
    tl = threading.local()
    orig_fetch = base.PlaceCrawler.fetch
    already_dedup = lane == "_missing"   # missing_urls_crawler already wraps fetch with old_url_check

    def fetch(self, url):
        blocked = self.__dict__.setdefault("_rq_blocked_hosts", set())
        host = urllib.parse.urlsplit(url).netloc.lower()
        if host in blocked:
            return {"status": 0, "final_url": url, "content_type": "", "sha256": "", "path": "", "size": 0,
                    "fetched_at": base.now_iso(), "error": "host_blocked", "body": b"", "cached": False, "not_fetched": True}
        hp = self.t.get("homepage") or ""
        if not already_dedup and (not hp or base.canon(url) != base.canon(hp)):
            c = getattr(tl, "c", None)
            if c is None:
                c = tl.c = UrlChecker()
            try:
                cov = c.covered(url)
            except Exception:
                cov = None
            if cov:
                self.events["dedup_covered"] += 1
                return {"status": 0, "final_url": url, "content_type": "", "sha256": "", "path": "", "size": 0,
                        "fetched_at": base.now_iso(), "error": "dedup_covered", "body": b"", "cached": False, "not_fetched": True}
        rec = orig_fetch(self, url)
        body = rec.get("body") or b""
        st = rec.get("status") or 0
        if st in (403, 429) or (st in (200, 503) and body and CHALLENGE.search(body[:30000])):
            blocked.add(host)
            self.events["blocked_challenge_or_403"] += 1
            with open(state / "_state" / "blocked_hosts.tsv", "a") as fh:
                fh.write(f"{base.now_iso()}\t{self.t['place_id']}\t{host}\t{st}\t{url}\n")
            rec = dict(rec, error=f"blocked_{st}", body=b"")
        return rec
    base.PlaceCrawler.fetch = fetch

    # ---- finish: output to staging/web/<CC>/, state under _requeue/<lane>/
    def finish_place(self, t, sink, res):
        cc = t.get("country_code") or lane
        ccdir = WEB / cc
        pk = base.place_key(t["place_id"])
        res.update(docs_found=sink.found, docs=sink.rows, pdf_docs=sink.pdf, html_docs=sink.html,
                   dropped_rows=dict(sink.dropped), country_code=cc, requeue=True, source_policy=POLICY)
        if not sink.rows and res.get("status") == "ok":
            res["status"] = "docs_without_text"
        res["file"] = ""
        if sink.rows:
            sink.close()  # fsynced
            ccdir.mkdir(parents=True, exist_ok=True)
            batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            final = ccdir / f"{pk}.{BATCH_KIND}.{batch}.jsonl"
            assert not final.exists()
            tmp = ccdir / f"{final.name}.tmp"
            os.rename(sink.tmp, tmp)
            sink.tmp = tmp
            chk = self.out / "_state" / "validate" / final.name
            chk.parent.mkdir(parents=True, exist_ok=True)
            chk.unlink(missing_ok=True)
            os.link(tmp, chk)
            v = base.world_schema.validate_file(chk, expect_place_key=pk)
            chk.unlink(missing_ok=True)
            if v["ok"]:
                os.rename(tmp, final)
                res["file"] = str(final)
            else:
                res["status"] = "validation_failed"
                res["validation_errors"] = [str(e) for e in v["errors"][:5]]
                bad = self.out / "_state" / "invalid" / final.name
                bad.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tmp, bad)
        else:
            sink.abort()
        sdir = self.out / "_state" / "places"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / f"{pk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        with self.lock:
            with self.results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            with self.done_path.open("a") as fh:
                fh.write(t["place_id"] + "\n")
            self.done.add(t["place_id"])
            self._agg_add(self.agg, res)
            self.session_done += 1
    base.Runner.finish_place = finish_place

    orig_wp = base.Runner.write_progress

    def write_progress(self, total, final=False):
        orig_wp(self, total, final)
        p = json.loads(self.progress_path.read_text())
        p.update(country_code=lane, lane="robots_requeue", source_policy=POLICY, requeue_list=len(ids),
                 finished=bool(final), batch_kind=BATCH_KIND)
        tmp = self.progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False)); tmp.replace(self.progress_path)
    base.Runner.write_progress = write_progress

    sys.argv = [sys.argv[0], "--out", str(state), "--workers", str(a.workers), "--max-places", str(a.max_places)]
    base.main()
    done = set((state / "_state" / "done_place_ids.txt").read_text().split()) if (state / "_state" / "done_place_ids.txt").exists() else set()
    targets = {t["place_id"] for t in load_targets()}
    if targets <= done:
        (state / "DONE").write_text(base.now_iso() + "\n")
        print(f"LANE_DONE {lane} {len(done & targets)}/{len(targets)}", flush=True)


if __name__ == "__main__":
    main()
