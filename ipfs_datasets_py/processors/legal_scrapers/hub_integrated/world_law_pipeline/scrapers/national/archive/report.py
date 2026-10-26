#!/usr/bin/env python3
"""Per-target yield summary from staged files + state. report.py [--md]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob, json, os, sys
from collections import Counter
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/archive"))
from specs import SPECS
S = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national")
rows = []
for t, sp in SPECS.items():
    d = f"{S}/_archive_work/{t}"
    st = json.load(open(f"{d}/stats.json")) if os.path.exists(f"{d}/stats.json") else {}
    done = Counter()
    dd = {}
    for fn in ("done.small.tsv", "done.tsv"):
        if os.path.exists(f"{d}/{fn}"):
            for l in open(f"{d}/{fn}"):
                p = l.split("\t")
                if len(p) > 1: dd[p[0]] = p[1].split(":")[0]
    done.update(dd.values())
    # staged docs: read provenance sidecars for this platform
    latest = {}
    for f in sorted(glob.glob(f"{S}/_archive_provenance/{sp['cc']}/*.archive2*.jsonl")):
        for l in open(f):
            r = json.loads(l)
            if r["doc_id"].startswith(sp["platform"] + ":"):
                latest[(r["place_id"], r["doc_id"])] = r
    n = len(latest); comp = sum(bool(r.get("content_complete")) for r in latest.values())
    stale = sum(bool(r.get("possibly_stale")) for r in latest.values())
    places = {k[0] for k in latest}; srcs = Counter(r.get("archive_source") for r in latest.values())
    cand = st.get("candidates", 0); inhf = st.get("candidates_in_hf", 0)
    att = sum(done.values()); rate = (done["staged"] / att) if att else None
    exp = round((cand - inhf) * rate) if rate is not None else None
    rows.append(dict(target=t, cc=sp["cc"], wb_caps=st.get("captures_wb"), cc_caps=st.get("captures_cc"),
                     candidates=cand, in_hf=inhf, attempted=att, staged=n,
                     pct_complete=round(100 * comp / n) if n else None, pct_stale=round(100 * stale / n) if n else None,
                     yield_pct=round(100 * rate) if rate is not None else None, expected_total=exp,
                     places=len(places), sources=dict(srcs), fails={k: v for k, v in done.items() if k != "staged"}))
if "--md" in sys.argv:
    print("| target | CC caps | WB caps | candidates | on HF | attempted | staged | %complete | %stale | yield | expected | places | fails |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['target']} | {r['cc_caps']} | {r['wb_caps']} | {r['candidates']} | {r['in_hf']} | {r['attempted']} | {r['staged']} | {r['pct_complete']} | {r['pct_stale']} | {r['yield_pct']} | {r['expected_total']} | {r['places']} | {r['fails']} |")
else:
    for r in rows: print(json.dumps(r, ensure_ascii=False))
