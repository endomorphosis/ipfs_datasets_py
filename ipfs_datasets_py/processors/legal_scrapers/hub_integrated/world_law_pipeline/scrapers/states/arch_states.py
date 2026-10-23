#!/usr/bin/env python3
"""States lane: archive-only harvest (Wayback / Common Crawl via the shared pipeline/archive module, ARCHIVE_LANE=states)
for adm1 sources whose live site is blocked (403 / TLS reset / Cloudflare) and whose robots.txt therefore counts as
disallow-all for live crawling. Archived copies are allowed (decision 2026-10-10); no live request is ever made.

  arch_states.py TARGET [--limit N] [--max-fetch N] [--review] [--flush-rows 200] [--flush-secs 900]

TARGET adapters (separate modules, this lane only):  in_state (in_state.py), at_ris (at_ris.py), id_bpk_prov (id_bpk_prov.py)
Candidate lists: the national lane's discovery (staging/national/_archive_work/<T>/candidates.jsonl[.gz]) is READ ONLY;
keys the national lane already staged (its done*.tsv 'staged') are skipped, so doc_ids continue without duplicates.
State: staging/states/_work/<TARGET>/done.tsv (resumable) + deferred.tsv (ArchiveDeferred/transient items, retried
no earlier than their not_before; persisted, see deferq.py). Output: common.stage_place() ->
staging/states[/_review]/<CC>/<place_key>.<tag>-<UTC>.jsonl (temp dot-file -> validate_file -> rename).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, gzip, importlib, json, logging, os, signal, sys, time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("ARCHIVE_LANE", "states")
import common  # noqa: E402  (adds pipeline/ to sys.path)
from common import STAGING, check_guards, GuardError, utcnow  # noqa: E402
from archive import ArchiveFetcher  # noqa: E402
from archive.core import ArchiveError, Capture  # noqa: E402
from archive import ratelimit  # noqa: E402
from archive.core import ArchiveTransient  # noqa: E402  (ArchiveDeferred is a subclass)
from deferq import (DeferQueue, fetch_best_or_defer, not_before_for, breaker_not_before, reset_incomplete,  # noqa: E402
                    incomplete_not_before)

NAT_WORK = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_archive_work"))
WORK = STAGING / "_work"
log = logging.getLogger("arch_states")
STOP = False


def _stop(*_):
    global STOP
    STOP = True


def open_text(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else p.open(encoding="utf-8")


def nat_candidates(nat_target):
    d = NAT_WORK / nat_target
    found = [p for p in (d / "candidates.jsonl.gz", d / "candidates.jsonl") if p.exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def nat_done(nat_target):
    out = {}
    for p in sorted((NAT_WORK / nat_target).glob("done*.tsv")):
        for line in p.open():
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    return out


class Job:
    def __init__(self, target, a):
        self.a = a
        self.ad = importlib.import_module(target).Adapter()
        self.dir = WORK / target
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fx = ArchiveFetcher(cc_crawls=a.cc_crawls, use_cc=not a.no_cc, lane="states")
        self.ad.fx = self.fx
        self.done = {}
        dp = self.dir / "done.tsv"
        if dp.exists():
            for line in dp.open():
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    if parts[1] == "requeue":
                        self.done.pop(parts[0], None)
                    else:
                        self.done[parts[0]] = parts[1]
        from oldskip import OldSkip
        self.oldskip = OldSkip(enabled=not getattr(self.a, "no_old_skip", False), log=log.info)
        self.nat = nat_done(self.ad.nat_target) if getattr(self.ad, "nat_target", None) else {}
        self.buf = defaultdict(list)       # place_id -> rows
        self.pending = defaultdict(list)   # place_id -> keys
        self.stats = Counter()
        self.files = []
        self.dq = DeferQueue(self.dir / "deferred.tsv", guard=check_guards)
        self.n_fetch = self.n_staged = 0
        self.last = time.time()

    def mark(self, key, outcome):
        with (self.dir / "done.tsv").open("a") as f:
            f.write(f"{key}\t{outcome}\t{utcnow()}\n")
        self.done[key] = outcome

    def flush(self):
        for pid in list(self.buf):
            rows = self.buf.pop(pid)
            keys = self.pending.pop(pid, [])
            if not rows:
                continue
            path, errs = common.stage_place(rows[0]["country_code"], pid, rows, tag=self.ad.tag, review=self.a.review)
            if errs:
                log.warning("validation issues %s: %s", pid, json.dumps(errs)[:600])
                self.stats["invalid_rows"] += sum(1 for e in errs if "doc_id" in e)
            if path:
                log.info("staged %s (%d rows)", path, len(rows))
                self.files.append(str(path))
            bad = {e.get("doc_id") for e in errs if e.get("doc_id")}
            for k, r in zip(keys, rows):
                self.mark(k, "invalid" if (r["doc_id"] in bad or not path) else ("review" if self.a.review else "staged"))

    def candidates(self):
        if hasattr(self.ad, "candidates"):        # adapter-side discovery (e.g. CC index listings)
            yield from self.ad.candidates(self.dir)
            return
        p = nat_candidates(self.ad.nat_target)
        with open_text(p) as f:
            for line in f:
                yield json.loads(line)

    def _limits(self):
        return (self.a.limit and self.n_staged >= self.a.limit) or (self.a.max_fetch and self.n_fetch >= self.a.max_fetch)

    def run(self):
        for r in self.candidates():
            if STOP or self._limits():
                break
            key = r["key"]
            if key in self.done:
                if key in self.dq:
                    self.dq.clear(key)
                continue
            if self.nat.get(key) == "staged":
                self.stats["skip_national_staged"] += 1; continue
            cov = self.oldskip.covered(_oldskip_url(r))
            if cov:
                self.stats["skip_old_url_covered"] += 1; continue
            why = self.ad.eligible(r)
            if why:
                self.stats["skip_" + why] += 1; continue
            if self.dq.held(key, r):                       # deferred into the future (persisted): later
                self.stats["held_deferred"] += 1; continue
            self.process(r)
        # second phase: deferred items as they come due; sleep until the earliest not_before when none is due
        for r in self.dq.drain(stop=lambda: STOP or self._limits(), guard=check_guards, log=log.info):
            if r["key"] in self.done:
                self.dq.clear(r["key"]); continue
            self.process(r)
        self.flush()
        log.info("deferred queue left: %d (persisted in %s)", len(self.dq), self.dq.path)
        self.save_stats(final=not STOP)
        return self.files

    def defer(self, r, e, nb=None):
        nb = nb or not_before_for(e)
        self.dq.defer(r["key"], nb, f"{type(e).__name__}:{e}", r)
        self.stats["deferred"] += 1
        log.info("deferred %s until %s: %s", r["key"], time.strftime("%H:%M:%S", time.localtime(nb)), str(e)[:160])

    def process(self, r):
        key = r["key"]
        if not ratelimit.wayback_available() and not any(c["source"] == "commoncrawl" for c in r["caps"]):
            self.defer(r, ArchiveTransient("wayback breaker open (box-wide)"), breaker_not_before()); return
        check_guards()
        self.n_fetch += 1
        caps = [Capture(**c) for c in r["caps"]]
        reset_incomplete(self.fx)
        try:
            doc = fetch_best_or_defer(self.fx, caps, max_tries=max(3, len(caps)), validator=getattr(self.ad, "validator", None))
            rec, why = (None, "no_good_capture") if doc is None else self.ad.build(r, doc)   # None = true miss
        except ArchiveTransient as e:                     # incl. ArchiveDeferred / ItemDeferred: requeue, move on
            self.defer(r, e); return
        except ArchiveError as e:                         # other archive errors in sub-fetches: not a miss either
            self.defer(r, e, time.time() + 600); return
        except GuardError:
            raise
        except Exception as e:
            log.exception("build failed %s", key); rec, why = None, f"build_error:{type(e).__name__}"
        inc_nb = incomplete_not_before(self.fx)        # doc.incomplete: another source failed (main doc or sub-fetch)
        errs = common.validate_record(rec) if rec is not None else []
        if inc_nb:
            full = (rec is not None and not errs and rec.get("content_complete", True) and doc is not None
                    and getattr(doc, "content_complete", True) and len((rec.get("text") or "").strip()) >= 200)
            if not full:                               # no valid full text from what we got: try again later
                self.defer(r, ArchiveTransient(f"incomplete fetch ({why})"), inc_nb); return
            rec.setdefault("extra_metadata", {})["archive_incomplete"] = True
            self.stats["archive_incomplete_tagged"] += 1
        self.dq.clear(key)
        if rec is None:
            self.stats[why.split(":")[0]] += 1; self.mark(key, why); return
        if errs:
            self.stats["invalid"] += 1; self.mark(key, "invalid:" + ";".join(errs)[:80]); return
        self.buf[rec["place_id"]].append(rec); self.pending[rec["place_id"]].append(key)
        self.n_staged += 1
        self.stats["built"] += 1
        self.stats["fmt_" + rec["content_format"]] += 1
        self.stats["complete" if rec.get("content_complete", True) else "incomplete"] += 1
        if sum(len(v) for v in self.buf.values()) >= self.a.flush_rows or time.time() - self.last > self.a.flush_secs:
            self.flush(); self.last = time.time()
        if self.n_fetch % 10 == 0:
            log.info("progress fetched=%d built=%d deferred_q=%d %s fx=%s", self.n_fetch, self.n_staged, len(self.dq),
                     dict(self.stats), dict(self.fx.stats))
            self.save_stats()

    def save_stats(self, final=False):
        st = dict(self.stats, fetcher=dict(self.fx.stats), files=self.files[-50:], updated=utcnow(), final=final,
                  done_total=len(self.done), deferred_queue=len(self.dq))
        tmp = self.dir / "stats.json.tmp"; tmp.write_text(json.dumps(st, indent=1)); os.replace(tmp, self.dir / "stats.json")



def _oldskip_url(r):
    from oldskip import item_url
    return item_url(r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=["in_state", "at_ris", "id_bpk_prov", "de_by_cc", "de_sh_wb"])
    ap.add_argument("--limit", type=int, default=0, help="stop after N built rows")
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--review", action="store_true", help="stage into staging/states/_review/<CC>/ (uploader-ignored)")
    ap.add_argument("--flush-rows", type=int, default=200)
    ap.add_argument("--flush-secs", type=int, default=900)
    ap.add_argument("--cc-crawls", type=int, default=6)
    ap.add_argument("--no-cc", action="store_true")
    ap.add_argument("--no-old-skip", action="store_true", help="do not skip URLs already covered by old repos/world datasets")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _stop); signal.signal(signal.SIGINT, _stop)
    import fcntl
    lk = open(WORK / f".{a.target}.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(f"another {a.target} runner is active")
    try:
        files = Job(a.target, a).run()
    except GuardError as e:
        log.error("guard: %s", e); sys.exit(3)
    print(json.dumps({"files": files}, indent=1))


if __name__ == "__main__":
    main()
