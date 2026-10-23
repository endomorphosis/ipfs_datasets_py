#!/usr/bin/env python3
"""Local-only pass of build_scanned_queue (stdlib only, system python3): staged SAPL no-text rows -> scanned-PDF queue."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import ast, glob, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import scanned_pdfs as Q  # noqa: E402
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
def pdf_of(v):
    if isinstance(v, str):
        try: v = ast.literal_eval(v) if v.startswith("[") else [v]
        except (ValueError, SyntaxError): v = [v]
    return next((u for u in (v or []) if isinstance(u, str) and u.startswith("http")), None)
out = []
for f in sorted(glob.glob(str(STAGE / "BR/*.sapl-*.jsonl"))):
    pk = Path(f).name.split(".")[0]
    try: lines = open(f, encoding="utf-8").readlines()
    except FileNotFoundError: continue          # pruned by the Normalizer mid-scan
    for ln in lines:
        try: r = json.loads(ln)
        except ValueError: continue
        if r.get("source_platform") == "br_sapl" and r.get("content_complete") is False and r.get("text_source") == "ementa":
            u = pdf_of(r.get("pdf_urls"))
            if u: out.append(Q.record(r["doc_id"], pk, "BR", u, r.get("source_policy")))
print(time.strftime("%F %T"), "local candidates", len(out), "appended", Q.append(out), flush=True)
