#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, sys
sys.path.insert(0, str(_SCRAPERS) + "/scrapers")
from collect_it import api_post
from common import html_to_text
row = {"dataGU": "2002-05-04", "codiceRedazionale": "002G0112"}
print("start", flush=True)
for i in [1, 2, 3, 8]:
    r = api_post("/api/v1/atto/dettaglio-atto", {**row, "formatoRichiesta": "V", "idArticolo": i})
    print("status", i, r.status_code, flush=True)
    if r.status_code != 200:
        print((r.text or "")[:120], flush=True); continue
    atto = ((r.json().get("data") or {}).get("atto")) or {}
    html = atto.get("articoloHtml") or ""
    arts = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    text = html_to_text(html)
    print(f"id={i} html={len(html)} arts={arts} head={text[:60]!r}", flush=True)
r = api_post("/api/v1/atto/dettaglio-atto-urn", {"urn": "urn:nir:stato:decreto:2002-03-29;80"})
print("urn", r.status_code, len(r.content or b""), flush=True)
if r.status_code == 200:
    data = r.json().get("data") or {}
    print("keys", list(data.keys()), "lista", len(data.get("lista") or []), flush=True)
    for j, a in enumerate((data.get("lista") or [])[:3]):
        h = (a or {}).get("articoloHtml") or ""
        arts = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', h)
        print(" lista", j, "html", len(h), arts[:2], flush=True)
print("done", flush=True)
