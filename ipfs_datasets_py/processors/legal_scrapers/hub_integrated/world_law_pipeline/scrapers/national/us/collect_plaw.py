#!/usr/bin/env python3
"""US Public Laws from govinfo bulk PLAW USLM XML (all Congresses available). One doc per public law.
Downloads the per-Congress zip, processes, deletes it. Resumable per Congress."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, time, re, zipfile
import requests
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_util import write_part, check_space, utcstamp, now_iso
from robots import allowed, UA
BASE = "https://www.govinfo.gov/bulkdata"
WORK = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/_work/US/plaw"); os.makedirs(WORK, exist_ok=True)
STATE = os.path.join(WORK, "done_congress.json"); PART = 500
NS = {"u": "http://schemas.gpo.gov/xml/uslm", "dc": "http://purl.org/dc/elements/1.1/"}
S = requests.Session(); S.headers["User-Agent"] = UA
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def get(url, **kw):
    if not allowed(url): raise SystemExit(f"robots disallow {url}")
    for i in range(5):
        try:
            r = S.get(url, timeout=300, **kw)
            if r.status_code == 200: return r
            log("HTTP", r.status_code, url)
        except Exception as e: log("ERR", e, url)
        time.sleep(10 * (i + 1))
    raise RuntimeError(url)
def rec_from(xml, name, cong):
    root = etree.fromstring(xml, etree.XMLParser(huge_tree=True, recover=True))
    m = re.search(r"PLAW-(\d+)publ(\d+)", name); num = m.group(2)
    t = root.findtext(".//dc:title", namespaces=NS) or f"Public Law {cong}-{num}"
    date = root.findtext(".//u:meta/u:approvedDate", namespaces=NS) or root.findtext(".//dc:date", namespaces=NS)
    cites = [c.text for c in root.findall(".//u:meta/u:citableAs", namespaces=NS)]
    main = root.find(".//u:main", namespaces=NS); body = main if main is not None else root
    txt = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", "".join(body.itertext()))).strip()
    pkg = f"PLAW-{cong}publ{num}"
    return {"place_id": "iso:US", "country_code": "US", "doc_id": f"plaw-{cong}-{num}",
        "source_platform": "us_govinfo_plaw", "source_url": f"https://www.govinfo.gov/app/details/{pkg}",
        "doc_type": "statute", "language": "en", "title_native": t.strip(), "number": f"Pub. L. {cong}-{num}",
        "adopted_date": date, "published_date": date, "in_force": None, "consolidated": False,
        "content_format": "xml", "html": etree.tostring(body, encoding="unicode"), "text": txt, "retrieved_at": now_iso(),
        "extra_metadata": {"congress": int(cong), "citable_as": cites,
                           "xml_url": f"{BASE}/PLAW/{cong}/public/{pkg}.xml"}}
def main():
    done = json.load(open(STATE)) if os.path.exists(STATE) else {}
    congs = [f["name"] for f in get(f"{BASE}/json/PLAW", headers={"Accept": "application/json"}).json()["files"] if f["name"].isdigit()]
    for c in sorted(congs, key=int):
        if c in done: continue
        check_space()
        files = get(f"{BASE}/json/PLAW/{c}/public", headers={"Accept": "application/json"}).json()["files"]
        z = [f for f in files if f["name"].endswith(".zip")]
        recs = []
        if z:
            zp = os.path.join(WORK, z[0]["name"])
            with get(z[0]["link"], stream=True) as r, open(zp, "wb") as f:
                for ch in r.iter_content(1 << 20): f.write(ch)
            with zipfile.ZipFile(zp) as zf:
                for n in sorted(zf.namelist()):
                    if re.search(r"PLAW-\d+publ\d+\.xml$", n):
                        try: recs.append(rec_from(zf.read(n), n, c))
                        except Exception as e: log("parse fail", n, e)
            os.remove(zp)
        else:
            for f in files:
                if f["name"].endswith(".xml"):
                    recs.append(rec_from(get(f["link"]).content, f["name"], c)); time.sleep(1)
        recs = list({r["doc_id"]: r for r in recs}.values())
        recs.sort(key=lambda r: int(r["doc_id"].split("-")[2]))
        stamp = utcstamp(); n = 0
        for i in range(0, len(recs), PART):
            _, k = write_part("US", "iso:US", f"plaw{c}-{stamp}p{i//PART+1:04d}", recs[i:i+PART], log); n += k
        done[c] = n; json.dump(done, open(STATE + ".tmp", "w")); os.replace(STATE + ".tmp", STATE)
        log("CONGRESS DONE", c, n); time.sleep(2)
    log("PLAW FINISHED", sum(done.values()), "docs", done)
if __name__ == "__main__": main()
