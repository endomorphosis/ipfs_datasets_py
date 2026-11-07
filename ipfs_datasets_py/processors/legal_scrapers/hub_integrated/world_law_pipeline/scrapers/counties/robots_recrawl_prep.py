"""2026-11-01 robots recrawl prep (Benjamin: robots.txt no longer honoured for legal texts by default).
Builds, at run time, a live config <stem>_robotslive.json (only URLs not yet staged/processed, no spreadsheets, no Code Publishing/eCode360)
and a 3-URL test config <stem>_robotslive_test.json from an existing us_pdf_list/archive config. Prints the number of pending URLs.
usage: robots_recrawl_prep.py SRC.json"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, sys, gzip
from pathlib import Path
from urllib.parse import unquote
src = Path(sys.argv[1]); c = json.load(open(src))
staged = set()
roots = list(Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties")).rglob("*.jsonl")) + list(Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/processed/counties")).rglob("*.jsonl*"))
for f in roots:
    if c["platform"] not in str(f): continue
    try:
        for l in (gzip.open(f, "rt", errors="replace") if str(f).endswith(".gz") else open(f, errors="replace")):
            m = re.search(r'"source_url": ?"([^"]+)"', l)
            if m: staged.add(m.group(1)); staged.add(unquote(m.group(1)))
    except Exception: pass
EXC = re.compile(r"codepublishing\.com|\.municipal\.codes|\.county\.codes|ecode360", re.I)
SHEET = re.compile(r"\.(xlsx?|ods|csv)(\?|$)", re.I)
pend = [u for u in c["urls"] if u not in staged and unquote(u) not in staged and not EXC.search(u) and not SHEET.search(u)]
c.pop("archive_policy", None); c.setdefault("crawl_delay", 3); c["robots_recrawl_src"] = src.name
stem = src.name[:-5]
json.dump(dict(c, urls=pend), open(src.parent / f"{stem}_robotslive.json", "w"), ensure_ascii=False, indent=1)
json.dump(dict(c, urls=pend[:3]), open(src.parent / f"{stem}_robotslive_test.json", "w"), ensure_ascii=False, indent=1)
print(len(pend))
