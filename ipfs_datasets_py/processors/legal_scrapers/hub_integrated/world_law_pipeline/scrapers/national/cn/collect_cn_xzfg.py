#!/usr/bin/env python3
"""China: 国家行政法规库 (Ministry of Justice, xzfg.moj.gov.cn) - current State Council administrative regulations.
robots.txt 404 => allowed (RFC 9309). flk.npc.gov.cn is robots-disallowed and NOT used. 3 s between requests."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from natlib import PoliteSession, Stager, setup_log, html_to_text, norm_date, Blocked

BASE = "https://xzfg.moj.gov.cn"
log = setup_log("CN", "xzfg")
S = PoliteSession(min_delay=3.0, log=log)
st = Stager("CN", "xzfg", chunk=100, log=log)

def list_ids():
    first = S.get(f"{BASE}/search2.html").text
    m = re.search(r'id="page-count" value="(\d+)"', first)
    pages = int(m[1]) if m else 1
    ids = []
    for p in range(1, pages + 1):
        h = first if p == 1 else S.get(f"{BASE}/search2.html?PageIndex={p}").text
        for i in re.findall(r"front/law/detail\?LawID=(\d+)", h):
            if i not in ids: ids.append(i)
        log.info("page %d/%d ids=%d", p, pages, len(ids))
    return ids

def main():
    ids = list_ids()
    for lid in ids:
        did = f"xzfg-{lid}"
        if st.seen(did): continue
        url = f"{BASE}/front/law/detail?LawID={lid}"
        try:
            h = S.get(url).text
        except Blocked as e:
            log.error("blocked %s", e); break
        except Exception as e:
            log.warning("fail %s %s", url, e); continue
        tm = re.search(r'class="text-title">([^<]+)<', h)
        title = tm[1].strip() if tm else None
        i = h.find('class="law-chapter"')
        body = h[i:] if i >= 0 else h
        j = body.find("<footer")
        body = body[:j] if j > 0 else body
        text = html_to_text('<div ' + body)
        hist = re.findall(r"(\d{4}-\d{2}-\d{2})", h[h.find("历史沿革"):h.find("历史沿革") + 4000]) if "历史沿革" in h else []
        dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日[^）)]{0,40}?公布", text)
        pub = f"{dm[1]}-{int(dm[2]):02d}-{int(dm[3]):02d}" if dm else None
        st.add({"place_id": "iso:CN", "country_code": "CN", "doc_id": did, "source_platform": "cn_moj_xzfg",
                "source_url": url, "doc_type": "regulation", "language": "zh-Hans", "title_native": title,
                "adopted_date": pub, "published_date": max(hist) if hist else pub,
                "in_force": True, "consolidated": True, "content_format": "html", "text": text,
                "place_name": "China", "admin_level": "country", "platform": "cn_moj_xzfg"})
    st.flush(); log.info("FINISHED staged=%d ids=%d", st.n, len(ids))

if __name__ == "__main__":
    try: main()
    finally: st.flush()
