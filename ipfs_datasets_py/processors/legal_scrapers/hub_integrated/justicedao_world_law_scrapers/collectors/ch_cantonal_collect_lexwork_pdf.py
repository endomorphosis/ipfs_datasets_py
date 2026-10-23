#!/usr/bin/env python3
"""Supplement: for LexWork laws whose selected version has no structured JSON content, fetch the official PDF
(selected_version.pdf_link_tol on the same canton host). Single process, one thread per host, >= DELAY s/host,
3x403 -> BLOCKED, backoff on 429/5xx, resumable, memory guard."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, glob, os, sys, time, threading, urllib.parse
from pathlib import Path
sys.path.insert(0, "/workspace/scripts")
import ch_cantonal_collect_other as CO
BASE = _CORPORA / "ch_cantonal"
def todo(c):
    out = []
    for p in sorted(glob.glob(f"{BASE}/raw/{c}/*.json.gz")):
        pdf = p.replace(".json.gz", ".pdf")
        if os.path.exists(pdf): continue
        tol = json.load(gzip.open(p))["text_of_law"]; sv = tol.get("selected_version") or {}
        if (sv.get("json_content") or {}).get("document", {}).get("content"): continue
        u = sv.get("pdf_link_tol") or tol.get("pdf_link")
        if u: out.append((p, u.replace("http://", "https://")))
    return out
def worker(c):
    F = CO.Fetcher(c); L = todo(c); CO.ST[c]["index"] = len(L)
    try:
        for p, u in L:
            r = F.get(u)
            if not r or not r.content.startswith(b"%PDF"): CO.ST[c]["err"] += 1; continue
            Path(p.replace(".json.gz", ".pdf")).write_bytes(r.content); CO.ST[c]["ok"] += 1
        CO.ST[c]["done"] = True
    except CO.Blocked: CO.ST[c]["done"] = "BLOCKED"
    except KeyboardInterrupt: CO.ST[c]["done"] = "STOPPED"
if __name__ == "__main__":
    cs = sys.argv[1].split(",")
    ths = [threading.Thread(target=worker, args=(c,), daemon=True) for c in cs]; [t.start() for t in ths]
    while any(t.is_alive() for t in ths):
        time.sleep(20); print(" ".join(f"{c}:{CO.ST.get(c,{}).get('ok',0)}/{CO.ST.get(c,{}).get('index','?')}" for c in cs), flush=True)
    (BASE / "collect_lexwork_pdf_state.json").write_text(json.dumps(CO.ST, indent=1))
    print("DONE", json.dumps({c: {k: v for k, v in CO.ST[c].items() if k not in ("failed", "not_found")} for c in cs}), flush=True)
