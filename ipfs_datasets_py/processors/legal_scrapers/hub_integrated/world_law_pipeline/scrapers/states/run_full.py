#!/usr/bin/env python3
"""States lane full runner: discover -> dedupe (done state) -> polite fetch -> QC -> chunk to _review -> auto-QC -> promote.

  venv/bin/python run_full.py --source au_qld_leg [--max N] [--chunk 150] [--hold-first] [--test N]
--test N      : fetch N items (spread over the list), stage to _review only, never promote (manual spot-check)
--hold-first  : first chunk stays in _review and the run stops (eyeball, then rerun without it)
State: staging/states/_state/<source>.done.tsv  (doc_id \t status \t file)
       + <source>.deferred.tsv: items whose archive fetch was deferred (ArchiveDeferred / transient); retried no
         earlier than not_before, after the other items; persisted across restarts (deferq.py)   Logs: staging/states/_logs/full_<source>.log
"""
import argparse, json, os, re, sys, time, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ARCHIVE_LANE", "states")
from common import PoliteSession, STAGING, stage_place, promote, check_guards, rss_mb, utcnow, GuardError  # noqa: E402
from adapters import ADAPTERS, PLACES, BOILER  # noqa: E402
from deferq import DeferQueue, ArchiveTransient, not_before_for  # noqa: E402  (ArchiveDeferred/ItemDeferred subclass it)

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True); ap.add_argument("--max", type=int, default=0)
ap.add_argument("--chunk", type=int, default=150); ap.add_argument("--chunk-mb", type=float, default=60)
ap.add_argument("--hold-first", action="store_true"); ap.add_argument("--test", type=int, default=0)
ap.add_argument("--test-resume", action="store_true", help="with --test N: retry the deferred items of an interrupted test, top up to N")
ap.add_argument("--test-have", type=int, default=0, help="with --test-resume: rows of this test already held in _review")
ap.add_argument("--no-old-skip", action="store_true", help="do not skip URLs already covered by old repos/world datasets")
ap.add_argument("--retry-status", default="", help="comma list of done.tsv statuses to retry (e.g. load_failed); 2026-10-19")
ap.add_argument("--only", default="", help="comma list of doc_ids (or @file, one per line): restrict the run to these items; 2026-10-20")
a = ap.parse_args()
A = ADAPTERS[a.source]()
pl = PLACES[A.place]
(STAGING / "_state").mkdir(parents=True, exist_ok=True); (STAGING / "_logs").mkdir(parents=True, exist_ok=True)
DONE = STAGING / "_state" / f"{A.key}.done.tsv"
QCREJ = STAGING / "_logs" / f"qc_rejects_{A.key}.jsonl"
logf = open(STAGING / "_logs" / f"full_{A.key}.log", "a")


def log(*x):
    s = f"{utcnow()} [{A.key}] " + " ".join(map(str, x)); print(s, flush=True); logf.write(s + "\n"); logf.flush()


def load_done():
    d = {}
    if DONE.exists():
        for line in DONE.open(encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if p and p[0]:
                d[p[0]] = p[1] if len(p) > 1 else "staged"
    # rows already in staging/<CC>/ (or processed/) from this lane count as staged
    for f in glob.glob(str(STAGING / pl["country_code"] / f"iso_{pl['iso_3166_2']}.*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                d.setdefault(json.loads(line)["doc_id"], "staged")
            except Exception:
                pass
    return d


def mark(rows_or_ids, status, fname=""):
    with DONE.open("a", encoding="utf-8") as f:
        for i in rows_or_ids:
            f.write(f"{i}\t{status}\t{fname}\n")


def qc(rec):
    t = rec.get("text") or ""
    if len(t.strip()) < A.min_chars:
        return f"short_text_{len(t.strip())}"
    title = (rec.get("title_native") or "").strip()
    if not title or re.search(r"(?i)^(unknown page|page not found|not found|error|untitled)\b", title):
        return f"bad_title:{title[:60]}"
    if rec.get("place_id") != pl["place_id"] or rec.get("country_code") != pl["country_code"]:
        return "wrong_place"
    edge = t[:400] + t[-400:]
    for b in BOILER:
        if b in edge:
            return f"boilerplate:{b}"
    return None


sess = PoliteSession(log=log); check_guards()
done = load_done()
if a.retry_status:
    _rs = {x.strip() for x in a.retry_status.split(",") if x.strip()}
    _n0 = len(done); done = {k: v for k, v in done.items() if v not in _rs}
    log(f"--retry-status {sorted(_rs)}: {_n0 - len(done)} done entries reopened")
items = A.discover(sess)
todo = [it for it in items if it["doc_id"] not in done]
if a.only:
    _only = set((open(a.only[1:]).read().split() if a.only.startswith("@") else [x.strip() for x in a.only.split(",")]))
    _only.discard(""); todo = [it for it in todo if it["doc_id"] in _only]
    log(f"--only: {len(_only)} id(s) requested, {len(todo)} in todo")
from oldskip import OldSkip, item_url  # 2026-10-19 Normalizer: skip URLs already covered upstream
OS_ = OldSkip(enabled=not a.no_old_skip, log=log)
OS_.prefetch([item_url(it) for it in todo])
_cov = [it for it in todo if OS_.covered(item_url(it))]
if _cov:
    _cids = {it["doc_id"] for it in _cov}
    with open(STAGING / "_logs" / f"old_url_skipped_{A.key}.tsv", "a") as _f:
        for it in _cov:
            _f.write(f"{it['doc_id']}\t{item_url(it)}\t{OS_.cache.get(item_url(it))}\n")
    todo = [it for it in todo if it["doc_id"] not in _cids]
log(f"{OS_.summary()}; todo now {len(todo)}")
log(f"discovered {len(items)}; already done {len(items) - len(todo)}; todo {len(todo)}")
DQ = DeferQueue(STAGING / "_state" / f"{A.key}.deferred.tsv", guard=check_guards)
if a.test and a.test_resume:   # 2026-10-19: finish an interrupted test: its still-deferred items first, then top up to N
    _dq = [it for it in todo if it["doc_id"] in DQ]
    _ids = {it["doc_id"] for it in _dq}
    _rest = [it for it in todo if it["doc_id"] not in _ids]
    _need = max(0, a.test - a.test_have - len(_dq))
    step = max(1, len(_rest) // max(1, _need)); todo = _dq + (_rest[::step][:_need] if _need else [])
    log(f"--test-resume: {len(_dq)} deferred test item(s) + {min(_need, len(_rest))} new (have {a.test_have} in review)")
elif a.test:
    step = max(1, len(todo) // a.test); todo = todo[::step][:a.test]
if a.max:
    todo = todo[:a.max]

rows, nbytes, stats, chunks = [], 0, {}, 0


def stream():
    for it in todo:
        if DQ.held(it["doc_id"], it):          # deferred into the future by an earlier run: after the rest
            stats["held_deferred"] = stats.get("held_deferred", 0) + 1; continue
        yield it
    yield from DQ.drain(guard=check_guards, log=log)   # due deferred items; sleeps until earliest not_before


def flush(final=False):
    global rows, nbytes, chunks
    if not rows:
        return True
    path, errs = stage_place(pl["country_code"], pl["place_id"], rows, tag=A.key, review=True)
    if not path:
        log("STAGE FAILED", json.dumps(errs, default=str)[:1000]); return False
    L = sorted(len(r["text"]) for r in rows)
    log(f"chunk -> {path} rows={len(rows)} text min/med/max={L[0]}/{L[len(L)//2]}/{L[-1]} val_errs={len(errs)} rss={rss_mb():.0f}MB")
    bad_ids = {e.get("doc_id") for e in errs if isinstance(e, dict) and e.get("doc_id")}
    if bad_ids:   # rows dropped by validation: log them, do NOT mark done (fix adapter, rerun picks them up)
        with QCREJ.open("a", encoding="utf-8") as f:
            for e in errs:
                if isinstance(e, dict) and e.get("doc_id"):
                    f.write(json.dumps({"doc_id": e["doc_id"], "reason": "validation", "errors": e.get("errors")}, ensure_ascii=False, default=str) + "\n")
        log(f"validation dropped {len(bad_ids)} rows, e.g. {json.dumps(errs[0], default=str)[:300]}")
    ids = [r["doc_id"] for r in rows if r["doc_id"] not in bad_ids]; rows, nbytes = [], 0; chunks += 1
    if a.test or (a.hold_first and chunks == 1):
        log(f"HOLD in review: {path}"); mark(ids, "review", path.name); return False
    dst = promote(path); mark(ids, "staged", dst.name); log(f"promoted -> {dst}")
    time.sleep(1.1)   # batch tags have 1 s resolution: never reuse a file name
    return True


try:
    for n, it in enumerate(stream(), 1):
        check_guards()
        try:
            rec, why = A.fetch(sess, it)
        except ArchiveTransient as e:       # archive throttle/transient: requeue for >= not_before, move on
            nb = not_before_for(e)
            DQ.defer(it["doc_id"], nb, f"{type(e).__name__}:{e}", it)
            stats["deferred"] = stats.get("deferred", 0) + 1
            if stats["deferred"] <= 20 or stats["deferred"] % 100 == 0:
                log(f"deferred {it['doc_id']} until {time.strftime('%H:%M:%S', time.localtime(nb))}: {str(e)[:150]}")
            continue
        except PermissionError as e:
            log(f"STOP (robots/challenge, no bypass): {e}"); stats["stopped"] = str(e); break
        except GuardError:
            raise
        except Exception as e:
            rec, why = None, f"exc:{type(e).__name__}:{str(e)[:120]}"
        if rec is not None:
            bad = qc(rec)
            if bad:
                with QCREJ.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"doc_id": it["doc_id"], "url": it["url"], "reason": bad, "head": rec["text"][:300]}, ensure_ascii=False) + "\n")
                rec, why = None, "qc:" + bad.split(":")[0]
        stats[why] = stats.get(why, 0) + 1
        if it["doc_id"] in DQ:
            DQ.clear(it["doc_id"])
        if rec is None:
            if not why.startswith(("exc:", "http_5")):
                mark([it["doc_id"]], why)
            continue
        rows.append(rec); nbytes += len(rec["text"].encode())
        if len(rows) >= a.chunk or nbytes >= a.chunk_mb * 1e6:
            if not flush():
                break
        if n % 100 == 0:
            log(f"progress {n}/{len(todo)} stats={stats} rss={rss_mb():.0f}MB")
    else:
        flush(final=True)
except GuardError as e:
    log(f"GUARD STOP: {e}")
log(f"END stats={stats} chunks={chunks} deferred_left={len(DQ)}")
