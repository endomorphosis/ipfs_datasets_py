# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))

# Prefer in-package Greek municipal helpers (hub_integrated/legal_scrapers/municipal).
_MUNI_HELPERS = Path(__file__).resolve().parents[4] / "legal_scrapers" / "municipal"
if _MUNI_HELPERS.is_dir():
    import sys as _sys
    _sys.path.insert(0, str(_MUNI_HELPERS))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
import json, os, sys, urllib.parse
os.environ.setdefault("GR_CACHE", str(_CORPORA / "municipal" / "gr_ocr_state" / "cache"))
sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
from gr_common import Polite
P=Polite(1.0); P.s.headers["Accept"]="application/json"
items=json.load(open((str(_CORPORA) + "/municipal/ocr_candidates.json")))["packs"]["greece_municipal"]["broken_text_layer"]["items"]
log=open("fetch_log.jsonl","a")
for it in items:
    a=it["ada"]; q=urllib.parse.quote(a); rec={"ada":a}
    try:
        if not os.path.exists(f"meta/{a}.json"):
            d,m=P.get(f"https://diavgeia.gov.gr/opendata/decisions/{q}.json",timeout=60,cache=False)
            open(f"meta/{a}.json","wb").write(d)
        if not os.path.exists(f"pdf/{a}.pdf"):
            P.s.headers["Accept"]="*/*"
            d,m=P.get(f"https://diavgeia.gov.gr/opendata/decisions/{q}/document",timeout=(20,180),cache=False,allow_redirects=False)
            P.s.headers["Accept"]="application/json"
            open(f"pdf/{a}.pdf","wb").write(d); rec.update(bytes=len(d),ctype=m["ctype"],retrieved_at=m["retrieved_at"],url=m["url"],ok=d[:4]==b"%PDF")
        else: rec.update(ok=True,skipped=True)
    except Exception as e: rec.update(ok=False,error=str(e)[:300])
    log.write(json.dumps(rec,ensure_ascii=False)+"\n"); log.flush(); print(rec)
