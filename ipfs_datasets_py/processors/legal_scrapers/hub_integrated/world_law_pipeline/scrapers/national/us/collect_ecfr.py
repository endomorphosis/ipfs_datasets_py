#!/usr/bin/env python3
"""eCFR from govinfo bulk XML (current titles). One doc per DIV8 SECTION. Resumable via state file.
(ecfr.gov versioner /api/versioner/v1/full/ is robots-disallowed, so bulk XML is used.)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, time, re, html
import requests
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_util import write_part, check_space, utcstamp, now_iso
from robots import allowed, UA
BASE = "https://www.govinfo.gov/bulkdata"
WORK = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_work/US/ecfr"); os.makedirs(WORK, exist_ok=True)
STATE = os.path.join(WORK, "done_titles.json")
PART = 500
S = requests.Session(); S.headers["User-Agent"] = UA
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def get(url, **kw):
    if not allowed(url): raise SystemExit(f"robots disallow {url}")
    for i in range(5):
        try:
            r = S.get(url, timeout=120, **kw)
            if r.status_code == 200: return r
            log("HTTP", r.status_code, url)
        except Exception as e: log("ERR", e, url)
        time.sleep(10 * (i + 1))
    raise RuntimeError(url)
def text_of(el): return re.sub(r"[ \t]+", " ", "".join(el.itertext())).strip()
def to_html(el):
    s = etree.tostring(el, encoding="unicode", method="xml")
    return s
def main():
    done = json.load(open(STATE)) if os.path.exists(STATE) else {}
    titles = get(f"{BASE}/json/ECFR", headers={"Accept": "application/json"}).json()["files"]
    titles = sorted([t for t in titles if t.get("cfrTitle")], key=lambda t: t["cfrTitle"])
    total = 0
    for t in titles:
        tn = t["cfrTitle"]
        if str(tn) in done: continue
        check_space()
        files = get(t["link"], headers={"Accept": "application/json"}).json()["files"]
        xmls = [f for f in files if f["name"].endswith(".xml")]
        stamp = utcstamp(); part = 0; buf = []; n = 0; seen = set()
        for fdesc in xmls:
            path = os.path.join(WORK, fdesc["name"])
            with get(fdesc["link"], stream=True) as r, open(path, "wb") as f:
                for ch in r.iter_content(1 << 20): f.write(ch)
            log("title", tn, "downloaded", os.path.getsize(path))
            for ev, el in etree.iterparse(path, tag="DIV8", huge_tree=True, recover=True):
                if el.get("TYPE") != "SECTION": continue
                sec = (el.get("N") or "").replace("§", "").strip()
                if not sec or sec in seen: el.clear(); continue
                seen.add(sec)
                head = el.find("HEAD"); title = text_of(head) if head is not None else f"§ {sec}"
                txt = text_of(el)
                if not txt: el.clear(); continue
                buf.append({"place_id": "iso:US", "country_code": "US", "doc_id": f"ecfr-{tn}-{sec}",
                    "source_platform": "us_ecfr", "source_url": f"https://www.ecfr.gov/current/title-{tn}/section-{sec}",
                    "doc_type": "regulation", "language": "en", "title_native": f"{tn} CFR {title}",
                    "number": f"{tn} CFR {sec}", "html": to_html(el), "text": txt, "in_force": True,
                    "consolidated": True, "content_format": "xml", "retrieved_at": now_iso(),
                    "extra_metadata": {"cfr_title": tn, "node": el.get("NODE"), "bulk_file": fdesc["link"]}})
                el.clear()
                while el.getprevious() is not None: del el.getparent()[0]
                if len(buf) >= PART:
                    part += 1; _, k = write_part("US", "iso:US", f"ecfr{tn}-{stamp}p{part:04d}", buf, log); n += k; buf = []
            os.remove(path)
        if buf:
            part += 1; _, k = write_part("US", "iso:US", f"ecfr{tn}-{stamp}p{part:04d}", buf, log); n += k
        done[str(tn)] = n; total += n
        json.dump(done, open(STATE + ".tmp", "w")); os.replace(STATE + ".tmp", STATE)
        log("TITLE DONE", tn, n)
        time.sleep(2)
    log("ECFR FINISHED", sum(done.values()), "docs over", len(done), "titles")
if __name__ == "__main__": main()
