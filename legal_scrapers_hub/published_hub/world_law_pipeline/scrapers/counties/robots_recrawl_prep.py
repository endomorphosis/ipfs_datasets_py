"""2026-11-01 robots recrawl prep (Benjamin: robots.txt no longer honoured for legal texts by default).
Builds, at run time, a live config <stem>_robotslive.json (only URLs not yet staged/processed, no spreadsheets, no Code Publishing/eCode360)
and a 3-URL test config <stem>_robotslive_test.json from an existing us_pdf_list/archive config. Prints the number of pending URLs.
usage: robots_recrawl_prep.py SRC.json"""
import json, re, sys, gzip
from pathlib import Path
from urllib.parse import unquote
src = Path(sys.argv[1]); c = json.load(open(src))
staged = set()
roots = list(Path("/workspace/world_law/staging/counties").rglob("*.jsonl")) + list(Path("/workspace/world_law/processed/counties").rglob("*.jsonl*"))
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
