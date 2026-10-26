"""Japan tranche 1 — threaded full-corpus builder.

Same adapters, gates, staging format and resume semantics as
jp_t1_build.py, but fetches with a small worker pool (per-doc latency
through the egress proxy is 10-100 s while parse is ~0.1 s, so a serial
loop is latency-bound). A single writer thread appends each doc's rows
atomically and updates done.json, so staging stays consistent and a
killed run resumes exactly like the serial builder. Rows are staged in
completion order; finalize assigns doc_order over the staged sequence.
"""
import json
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jp_build as B  # noqa: E402
import jp_t1_build as T  # noqa: E402  (staging helpers, FastFetcher, finalize)

from world_municipal.normalize import make_row  # noqa: E402

OUT = T.OUT
DATA = T.DATA
SCRATCH = T.SCRATCH
STAGING = T.STAGING
RETRIEVED = T.RETRIEVED
REGISTRY = T.REGISTRY
JP = T.JP

_local = threading.local()


def thread_fetcher():
    fx = getattr(_local, "fx", None)
    if fx is None:
        fx = T.FastFetcher()
        _local.fx = fx
    return fx


def build_municipality(code, base, workers=4):
    reg = REGISTRY[code]
    name = reg["name"]
    fam = B.family_of(base, code)
    fx0 = T.FastFetcher()
    if fam == "d1law":
        chapters, docs = B.enumerate_d1law(fx0, code, base)
        parse = B.parse_d1law
    else:
        chapters, docs = B.enumerate_corpus(fx0, code, base)
        parse = B.parse_honbun
    done = T.load_done(code)
    done["corpus_docs"] = len(docs)
    done["chapters"] = len(chapters)
    if done["failed"]:
        done.setdefault("fail_log", []).extend(done["failed"])
        done["failed"] = []
        T.save_done(code, done)
    done_ids = {d["honbun_id"] for d in done["docs"]}
    todo = [d for d in docs if d["honbun_id"] not in done_ids]
    print(f"{code} {name}: corpus {len(docs)} docs / {len(chapters)} chapters; "
          f"done {len(done_ids)}, todo {len(todo)}, workers {workers}",
          flush=True)
    rows_path = STAGING / f"{code}_rows.jsonl"
    STAGING.mkdir(parents=True, exist_ok=True)
    rf = rows_path.open("a", encoding="utf-8")
    results = queue.Queue()

    def work(d):
        cache_file = SCRATCH / code / "honbun" / f"{d['honbun_id']}.html"
        try:
            raw = thread_fetcher().get(d["url"], cache_file)
            meta, units = parse(B.decode(raw))
            results.put(("ok", d, meta, units))
        except Exception as e:  # noqa: BLE001
            results.put(("fail", d, f"{type(e).__name__}: {e}", None))

    def run_pass(doc_list):
        if not doc_list:
            return
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, d) for d in doc_list]
            remaining = len(doc_list)
            while remaining:
                kind, d, a, b = results.get()
                remaining -= 1
                if kind == "fail":
                    done["failed"].append({"honbun_id": d["honbun_id"],
                                            "name": d["name"], "error": a})
                    T.save_done(code, done)
                    print(f"{code} FAIL {d['honbun_id']} {d['name']}: {a}",
                          flush=True)
                    continue
                meta, units = a, b
                title = meta["title"] or d["name"]
                path = f"{d['chapter_title']} / {title}"
                n_rows = 0
                for u in units:
                    row = make_row(
                        jurisdiction_id=code, jurisdiction_name=name,
                        country="JP", doc_id=f"{d['honbun_id']}-{u['key']}",
                        regeling_id=d["honbun_id"],
                        regeling_work_id=d["honbun_id"], title=title,
                        structural_path=path, node_label=u["label"],
                        body_html=u["html"], source_url=d["url"],
                        date_effective=meta["promulgated_iso"],
                        retrieved=RETRIEVED)
                    rf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n_rows += 1
                rf.flush()
                done["docs"].append({"honbun_id": d["honbun_id"],
                                     "name": title,
                                     "chapter": d["chapter_title"],
                                     "units": len(units), "rows": n_rows,
                                     "promulgated": meta["promulgated_iso"]})
                T.save_done(code, done)
                if len(done["docs"]) % 50 == 0:
                    print(f"{code}: {len(done['docs'])}/{len(docs)} docs",
                          flush=True)
            for f in futs:
                f.result()

    run_pass(todo)
    if done["failed"]:
        retry_ids = {f["honbun_id"] for f in done["failed"]}
        done["failed"] = []
        T.save_done(code, done)
        retry = [d for d in docs if d["honbun_id"] in retry_ids]
        print(f"{code}: retrying {len(retry)} failed docs", flush=True)
        run_pass(retry)
    rf.close()
    return T.finalize_municipality(code, name, base, fam, done)


def main():
    args = sys.argv[1:]
    workers = 4
    if args and args[0] == "--workers":
        workers = int(args[1])
        args = args[2:]
    if not args:
        print("usage: jp_t1_build2.py [--workers N] <JIS code> [more codes...]")
        return 1
    manifest_path = OUT / "tranche1_manifest.json"
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else {"municipalities": {}})
    for code in args:
        code = JP.normalize(code)
        if code not in T.ENDPOINTS:
            print(code, "no endpoint known — skipped", flush=True)
            continue
        try:
            res = build_municipality(code, T.ENDPOINTS[code], workers)
        except Exception as e:  # noqa: BLE001
            res = {"error": f"{type(e).__name__}: {e}"}
            print(code, "BUILD FAILED", e, flush=True)
        # merge-on-write: sibling builders finish at different times and
        # each holds a stale manifest snapshot; re-read before writing
        # or a late finisher would drop an earlier finisher's entry.
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["municipalities"][code] = res
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
    print("tranche1 manifest updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
