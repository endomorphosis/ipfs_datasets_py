#!/usr/bin/env python3
"""Nigeria (NON-OFFICIAL shard): PLAC (Policy and Legal Advocacy Centre) compilations.
 - LFN 2004 compendium: https://placng.org/lawsofnigeria/ (lawsofnigeria.placng.org redirects here)
 - post-2002 Acts: https://placng.org/i/acts/ (PDF links)
robots.txt on placng.org and lawsofnigeria.placng.org: 404 => allowed (RFC 9309). 3 s between requests.
License/terms: none found (checked /lawsofnigeria/aboutus.php, faq.php, /i/permissions/ (empty),
/i/privacy-policy/ (privacy only)); footer '© Copyright Policy and Legal Advocacy Centre 2026'.
Underlying texts = federal statutes (LFN 2004 / Acts of the National Assembly).
Schema has no per-doc provenance columns, so: source_platform='ng_plac_nonofficial' (survives into parquet),
plus extra staged keys source_official=false, source_org='PLAC', license_note (kept in staged JSONL; the
validator ignores unknown keys). Batch suffix contains 'plac' so this shard can be pulled later.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, subprocess, sys, tempfile, os
from urllib.parse import urljoin
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from natlib import PoliteSession, Stager, setup_log, html_to_text, Blocked

LFN = "https://placng.org/lawsofnigeria/"
ACTS = "https://placng.org/i/acts/"
LICENSE = ("No license or terms of use found on placng.org/lawsofnigeria (about, faq) or placng.org/i/permissions "
           "(empty) / privacy-policy; site footer: '© Copyright Policy and Legal Advocacy Centre 2026'. Texts are "
           "Nigerian federal statutes (LFN 2004 compilation / Acts) republished by PLAC; non-official copy.")
log = setup_log("NG", "plac")
S = PoliteSession(min_delay=3.0, log=log)
st = Stager("NG", "plac", chunk=100, log=log)

def pdf_text(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b); p = f.name
    try:
        return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=120).stdout
    finally:
        os.unlink(p)

def lfn_items():
    first = S.get(LFN).text
    m = re.findall(r'\?page=(\d+)', first); last = max(map(int, m)) if m else 1
    for p in range(1, last + 1):
        h = first if p == 1 else S.get(f"{LFN}?page={p}").text
        for href, title in re.findall(r"<a href='([^']+)' target=\"_blank\">\s*([^<]+)", h):
            yield urljoin(LFN, href), " ".join(title.split()), "lfn2004"
        log.info("lfn page %d/%d", p, last)

def acts_items():
    seen = set(); page = 1
    while True:
        url = ACTS if page == 1 else f"{ACTS}page/{page}/"
        try: h = S.get(url).text
        except Exception: break
        new = 0
        for href in re.findall(r'href="([^"]+\.pdf)"', h):
            if href in seen: continue
            seen.add(href); new += 1
            title = re.sub(r"[-_]+", " ", href.rsplit("/", 1)[-1][:-4]).strip()
            yield href, title, "acts"
        log.info("acts page %d new=%d", page, new)
        if not new: break
        page += 1

def main():
    for url, title, coll in list(lfn_items()) + list(acts_items()):
        key = re.sub(r"[^A-Za-z0-9]+", "-", url.split("placng.org/")[-1]).strip("-").lower()
        did = f"plac-{key}"
        if st.seen(did): continue
        try:
            r = S.get(url)
        except Blocked as e:
            log.error("blocked %s", e); break
        except Exception as e:
            log.warning("fail %s %s", url, e); continue
        is_pdf = url.lower().endswith(".pdf") or "pdf" in r.headers.get("content-type", "")
        text = pdf_text(r.content) if is_pdf else html_to_text(r.text.split("Searchable Compendium", 1)[-1].split("Subscribe to our Newsletter", 1)[0])
        if len(text.strip()) < 50:
            log.warning("empty text %s", url); continue
        ym = re.search(r"(19|20)\d\d", title)
        st.add({"place_id": "iso:NG", "country_code": "NG", "doc_id": did, "source_platform": "ng_plac_nonofficial",
                "source_url": url, "doc_type": "statute", "language": "en", "title_native": title,
                "adopted_date": ym[0] if (ym and coll == "acts") else None,
                "in_force": None, "consolidated": coll == "lfn2004", "content_format": "pdf_text" if is_pdf else "html",
                "text": text, "place_name": "Nigeria", "admin_level": "country", "platform": "ng_plac_nonofficial",
                "source_official": False, "source_org": "PLAC", "source_collection": coll, "license_note": LICENSE})
    st.flush(); log.info("FINISHED staged=%d", st.n)

if __name__ == "__main__":
    try: main()
    finally: st.flush()
