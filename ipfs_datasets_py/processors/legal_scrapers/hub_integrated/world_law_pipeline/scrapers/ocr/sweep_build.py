"""Sweep step 3: merge sweep_work/local_rows.jsonl + hub_rows.jsonl -> staging/pdf/_state/sweep_20261017.jsonl (lane 'sweep',
append-only, one row per doc). Exclusions: state/pdf_ledger.jsonl, _logs/fetched.jsonl, _state/done.txt (any lane), the
5-attempt-capped docs (retried separately at 18:00 PT), Google Drive URLs, robots_* / Cloudflare source_policy (logged as blocked),
rows without place_id. Stats -> sweep_work/build_stats.json.  --loop: rebuild every 15 min while sweep_hub.py runs."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, subprocess, sys, time
from collections import Counter, defaultdict
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import sweep_common as S

def rows():
    for fn in ("local_rows.jsonl", "hub_rows.jsonl"):
        p = S.WORK / fn
        if not p.exists(): continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.endswith("\n"):
                    try: yield fn.split("_")[0], json.loads(ln)
                    except ValueError: pass

def build():
    led, fet, done, capped = S.load_exclusions()
    have = set()
    if S.SWEEP.exists():
        for ln in open(S.SWEEP, encoding="utf-8"):
            try: have.add(json.loads(ln)["doc_id"])
            except (ValueError, KeyError): pass
    st = defaultdict(Counter); seen = set(); new = []; capped_hit = []
    for src, r in rows():
        d, cc = r["doc_id"], r.get("country_code") or "XX"
        if d in seen: continue
        seen.add(d); st[cc]["candidates"] += 1; st[cc]["src_" + src] += 1
        if d in capped: st[cc]["excl_capped"] += 1; capped_hit.append(d); continue
        if d in led: st[cc]["excl_ledger"] += 1; continue
        if d in fet: st[cc]["excl_fetched"] += 1; continue
        if d in done: st[cc]["excl_done"] += 1; continue
        if not r.get("place_id"): st[cc]["excl_no_place"] += 1; continue
        u = r.get("pdf_url") or r["source_url"]
        if S.GDRIVE_RE.search(u): st[cc]["excl_gdrive"] += 1; continue
        pol = S.pols(r.get("source_policy"))
        if S.CF_POL in pol: st[cc]["blocked_cf_policy"] += 1; continue
        if pol & S.ROBOTS_POL: st[cc]["blocked_" + "_".join(sorted(pol & S.ROBOTS_POL))] += 1; continue
        st[cc]["queued"] += 1
        if d in have: continue
        have.add(d)
        new.append({"doc_id": d, "place_id": r["place_id"], "place_key": S.place_key(r["place_id"]), "country_code": cc,
                    "source_url": r["source_url"], "lane": "sweep", "fetch_url": u, "archive_url": r.get("archive_url"),
                    "source_policy": r.get("source_policy"), "why": r["why"], "text_len": r.get("text_len"),
                    "found_in": r.get("hub") or r.get("f")})
    if new:
        with open(S.SWEEP, "a", encoding="utf-8") as w:
            for o in new: w.write(json.dumps(o, ensure_ascii=False) + "\n")
            w.flush(); os.fsync(w.fileno())
    tot = Counter()
    for c in st.values(): tot.update(c)
    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "appended_now": len(new), "total": tot, "by_country": st,
           "capped_seen": sorted(set(capped_hit))}
    t = S.WORK / "build_stats.json.tmp"; t.write_text(json.dumps(out, indent=1, sort_keys=True)); os.replace(t, S.WORK / "build_stats.json")
    return out

if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            alive = subprocess.run(["pgrep", "-f", "sweep_hub.py"], capture_output=True).returncode == 0
            o = build(); print(time.strftime("%H:%M:%S"), "appended", o["appended_now"], dict(o["total"]), flush=True)
            if not alive: break
            time.sleep(900)
    else:
        o = build(); print(json.dumps({k: v for k, v in o.items() if k != "by_country"}, default=dict))
