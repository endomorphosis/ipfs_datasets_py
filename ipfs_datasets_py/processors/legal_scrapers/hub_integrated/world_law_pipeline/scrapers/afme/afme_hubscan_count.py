"""Count rebuilt afme OCR/PDF queue rows vs staging/ocr/_state/afme_done.txt (key = sha1(place_id|doc_id)[:20], = ocr_afme.did_of)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,hashlib,collections
Q=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/_ocr_queue.jsonl"); done=set(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ocr/_state/afme_done.txt")).read().split())
rows=[json.loads(l) for l in open(Q)]; c=collections.Counter(); d=0; pdf=0
for r in rows:
    k=hashlib.sha1(f"{r['place_id']}|{r['doc_id']}".encode()).hexdigest()[:20]
    if k in done: d+=1
    c[r["country_code"]]+=1; pdf+=r.get("pdf_url_like",False)
print(json.dumps({"rows":len(rows),"in_afme_done":d,"left":len(rows)-d,"pdf_url_like":pdf,"by_cc":c.most_common()}))
