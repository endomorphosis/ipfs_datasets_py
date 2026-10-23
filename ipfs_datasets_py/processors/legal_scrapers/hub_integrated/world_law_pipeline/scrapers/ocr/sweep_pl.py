"""Sweep addition (2026-10-17 PT): EU lane Poland failed acts -> sweep lane input staging/pdf/_state/sweep_pl_20261017.jsonl.
Read-only on staging/eu: failed_<WOJ>.jsonl (append logs; latest record per ELI wins), done_<WOJ>.txt (later successes),
catalog_<WOJ>.jsonl + pl_dzienniki.PlaceMap (same place resolution as the lane: doc_id = ELI, place_id from issuer).
Queued: no-text scans (max_attempts 5 = normal); pdftotext timeouts, network timeouts / 504 / IncompleteRead
(max_attempts 1 = exactly one retry, then gave_up). Not queued: HTTP 403 / host parked. Stats -> sweep_work/pl_stats.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob, json, os, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/eu"))
import sweep_common as S
import pl_dzienniki as P

ST = S.WL / "staging/eu/_state/pl"; OUTF = S.SWEEP   # rows go into the main sweep input (sweep_pl_20261017.jsonl = first copy, loader dedupes)

def reason(e):
    if e.startswith("no text"): return "scanned_no_text"
    if "pdftotext" in e and "timed out" in e: return "pdftotext_timeout"
    if "Read timed out" in e or "ConnectTimeout" in e or "Connect timeout" in e: return "read_timeout"
    if "IncompleteRead" in e or "Connection broken" in e: return "incomplete_read"
    if re.search(r"HTTP 50[234]", e): return "http_5xx"
    if "host parked" in e: return "http_403_host_parked"
    if "HTTP 403" in e: return "http_403"
    return "other"
QUEUE = {"scanned_no_text": 5, "pdftotext_timeout": 1, "read_timeout": 1, "incomplete_read": 1, "http_5xx": 1}

def main():
    led, fet, done, capped = S.load_exclusions()
    have = set()
    for f in (S.SWEEP, S.PDF / "_state/sweep_pl_20261017.jsonl"):
        if f.exists():
            for l in open(f):
                try: have.add(json.loads(l)["doc_id"])
                except (ValueError, KeyError): pass
    pm = P.PlaceMap(); st = defaultdict(Counter); rows_raw = 0; new = []; other_ex = []
    for fp in sorted(glob.glob(str(ST / "failed_*.jsonl"))):
        woj = re.match(r"failed_(\w\w)\.jsonl$", os.path.basename(fp))
        if not woj: continue
        woj = woj.group(1); last = {}
        for l in open(fp, encoding="utf-8"):
            try: r = json.loads(l)
            except ValueError: continue
            rows_raw += 1
            if r.get("eli"): last[r["eli"]] = r
        okd = set((ST / f"done_{woj}.txt").read_text().split()) if (ST / f"done_{woj}.txt").exists() else set()
        cat = {}
        for l in open(ST / f"catalog_{woj}.jsonl", encoding="utf-8"):
            it = json.loads(l); e = it.get("eli") or it.get("address")
            if e in last and e not in cat: cat[e] = it
        h = P.HOSTS[woj][1]; base = f"https://{h}"
        for eli, r in last.items():
            why = reason(r.get("error", "")); c = st[woj]; c["failed_unique"] += 1; c["reason_" + why] += 1
            if why == "other": other_ex.append(r.get("error", "")[:120])
            if eli in okd: c["later_succeeded"] += 1; continue
            if why not in QUEUE: c["not_queued_" + why] += 1; continue
            if eli in capped: c["excl_capped"] += 1; continue
            if eli in led: c["excl_ledger"] += 1; continue
            if eli in fet: c["excl_fetched"] += 1; continue
            if eli in done: c["excl_done"] += 1; continue
            it = cat.get(eli)
            if not it: c["no_catalog_row"] += 1; continue
            ok, _, org, lvl = P.in_pass1(it)
            pl = pm.resolve(woj, org, lvl)
            if not pl.get("place_id"): c["no_place_id"] += 1; continue
            c["queued"] += 1; c["queued_" + why] += 1
            if eli in have: continue
            have.add(eli); u = f"{base}/api/eli/acts/{eli}/text.pdf"
            new.append({"doc_id": eli, "place_id": pl["place_id"], "place_key": S.place_key(pl["place_id"]), "country_code": "PL",
                        "source_url": u, "lane": "sweep", "fetch_url": u, "archive_url": None, "source_policy": None,
                        "why": "pl_failed_" + why, "max_attempts": QUEUE[why], "voivodeship": woj,
                        "found_in": f"staging/eu/_state/pl/failed_{woj}.jsonl"})
    if new:
        with open(OUTF, "a", encoding="utf-8") as w:
            for o in new: w.write(json.dumps(o, ensure_ascii=False) + "\n")
            w.flush(); os.fsync(w.fileno())
    tot = Counter()
    for c in st.values(): tot.update(c)
    out = {"rows_raw": rows_raw, "appended_now": len(new), "total": tot, "by_woj": st, "other_examples": other_ex[:10]}
    (S.WORK / "pl_stats.json").write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != "by_woj"}, default=dict, ensure_ascii=False))

if __name__ == "__main__": main()
