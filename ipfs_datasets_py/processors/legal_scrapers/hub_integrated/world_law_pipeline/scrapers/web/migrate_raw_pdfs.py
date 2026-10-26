#!/usr/bin/env python3
"""One-off: replace stored raw PDFs in staging/web/DE/_raw with extracted text (<sha>.pdftxt.gz)
and repoint the fetch cache, to keep disk use bounded."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import gzip, sqlite3, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.argv = [sys.argv[0]]
import importlib.util
spec = importlib.util.spec_from_file_location("c", Path(__file__).with_name("de_ortsrecht_crawler.py"))
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
RAW = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/DE/_raw"))
db = sqlite3.connect((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/DE/_state/fetch_cache.sqlite"))
pdfs = sorted(RAW.glob("*/*.pdf"))
print("pdfs", len(pdfs), flush=True)

def one(p: Path):
    out = p.with_name(p.name[:-4] + ".pdftxt.gz")
    if not out.exists():
        txt, err = c.pdf_text(str(p))
        tmp = out.with_name(out.name + ".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(txt.encode("utf-8"))
        tmp.replace(out)
    return p, out

done = 0
with ThreadPoolExecutor(4) as ex:
    for p, out in ex.map(one, pdfs):
        db.execute("UPDATE fetch SET path=? WHERE path=?", (str(out), str(p)))
        p.unlink()
        done += 1
        if done % 500 == 0:
            db.commit(); print(done, flush=True)
db.commit()
print("done", done)
