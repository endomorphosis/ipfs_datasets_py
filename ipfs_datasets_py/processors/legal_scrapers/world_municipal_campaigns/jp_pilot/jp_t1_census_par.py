"""Parallel driver for the tranche-1 census verification phase.

Uses jp_t1_census.verify() unchanged, but runs candidates through a
small thread pool (each thread owns a Fetcher) and appends records to
tenant_census.jsonl under a lock. Skips endpoints already recorded.
Finishes by rebuilding tenant_registry.json like the serial main().
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jp_build as B  # noqa: E402
import jp_t1_census as C  # noqa: E402
import jp_t1_build as T  # noqa: E402  (timeout-safe robots + pooled fetcher)

OUT = C.OUT
lock = threading.Lock()
_local = threading.local()
state = {"enum_budget": C.ENUM_CAP}


def thread_fx():
    fx = getattr(_local, "fx", None)
    if fx is None:
        fx = T.FastFetcher()
        _local.fx = fx
    return fx


def main():
    cand_path = OUT / "tenant_candidates.json"
    cands = {c["endpoint"]: c for c in
             json.loads(cand_path.read_text(encoding="utf-8"))}
    done_eps = set()
    if C.CENSUS_PATH.exists():
        for l in C.CENSUS_PATH.read_text(encoding="utf-8").splitlines():
            if l.strip():
                done_eps.add(json.loads(l)["endpoint"])
    todo = [c for ep, c in sorted(cands.items()) if ep not in done_eps]
    print(f"verifying {len(todo)} candidates "
          f"({len(done_eps)} already recorded)", flush=True)
    out = C.CENSUS_PATH.open("a", encoding="utf-8")

    def one(cand):
        # g-reiki.net cloud tenants: uniformly 403 from this egress
        # (pilot-verified incl. robots.txt) — record census + kana match
        # without live fetches.
        if cand.get("variant") == "cloud-greiki":
            rec = dict(cand, live=False, status="egress_blocked",
                       error="g-reiki.net 403 for all paths from this "
                             "egress (pilot-verified 2026-10-14)")
            codes, prefer = C.slug_kana_match(cand.get("slug") or "")
            pool = codes
            if prefer:
                pp = [c for c in codes
                      if C.REG.get(c, {}).get("kind") == prefer]
                if pp:
                    pool = pp
            if len(pool) == 1:
                rec["jis"] = pool[0]
                rec["matched_name"] = C.REG[pool[0]]["name"]
                rec["match"] = "kana (unverified, egress blocked)"
                rec["kind"] = C.REG[pool[0]].get("kind", "")
            elif len(codes) > 1:
                rec["kana_candidates"] = codes
            with lock:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
            return
        with lock:
            budget = state["enum_budget"]
        try:
            rec, budget = C.verify(thread_fx(), cand, budget)
        except Exception as e:  # noqa: BLE001
            rec = dict(cand, status="error",
                       error=f"{type(e).__name__}: {e}")
        with lock:
            state["enum_budget"] = budget
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
        print(rec.get("status"), rec.get("jis", ""), cand["endpoint"],
              rec.get("corpus_docs", ""), flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    out.close()
    reg = {}
    for l in C.CENSUS_PATH.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("status") in ("verified", "known_pilot") and r.get("jis"):
            prev = reg.get(r["jis"])
            if prev is None or (r.get("corpus_docs") or 0) > (prev.get("corpus_docs") or 0):
                reg[r["jis"]] = r
    C.REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    print(f"census verify done: {len(reg)} verified tenants in registry")


if __name__ == "__main__":
    main()
