#!/usr/bin/env python3
"""Tanzania (TZ): Acts of Parliament (PDF) from the official Parliament of Tanzania portal (polis.bunge.go.tz,
listed at https://www.parliament.go.tz/acts).  Listing: GET https://polis.bunge.go.tz/api/acts/async (the page's
own DataTables endpoint, ~1,172 acts).  Text: pdftotext of the official PDF (<=40 MB).
TLS: the server omits its intermediate.  We verify with certifi + the official DigiCert intermediate fetched from
the leaf's AIA URL and checked (pipeline/state/tls/README.txt).  Verification stays ON (no verify=False).
robots.txt (RFC 9309, fetched with the same verified chain): "User-agent: * / Disallow:" = allow all.  >=4 s delay.
Dedup: skip PDFs whose URL is already in an older ipfs_*_laws repo.  Resumable (.done ids).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, re, subprocess, sys, tempfile, time
from urllib.parse import quote
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/national/common"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/asia_latam/common"))
from natlib import setup_log, Blocked  # noqa
from robots import UA  # noqa
from rfc9309 import Robots  # noqa
from newcc import DedupSkip, SafeStager  # noqa

CC, NAME = "TZ", "tz_bunge"
BASE = "https://polis.bunge.go.tz"
BUNDLE = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/state/tls/ca_bundle_plus_aia.pem")
log = setup_log(CC, NAME)
s = requests.Session(); s.headers["User-Agent"] = UA; s.verify = BUNDLE
last = [0.0]

def robots():
    try:
        r = s.get(BASE + "/robots.txt", timeout=30)
    except Exception as e:
        raise Blocked(f"robots unreachable {e}")  # fetch failure: stop, retry later
    if r.status_code >= 500: return Robots(disallow_all=True)
    if r.status_code >= 400: return Robots(allow_all=True)
    return Robots(r.text)
RB = robots()

def get(url, **kw):
    if not (RB.can_fetch(UA, url) and RB.can_fetch("*", url)): raise Blocked("robots disallow " + url)
    for i in range(4):
        w = 4.0 - (time.time() - last[0])
        if w > 0: time.sleep(w)
        last[0] = time.time()
        try:
            r = s.get(url, timeout=120, **kw)
            if r.status_code in (401, 403): raise Blocked(f"HTTP {r.status_code}")
            if r.status_code not in (429, 500, 502, 503, 504): return r
        except Blocked: raise
        except Exception as e: log.warning("get err %s %s", url, e)
        time.sleep(15 * (i + 1))
    raise RuntimeError("GET failed " + url)

def pdf_text(url, cap=40_000_000):
    r = get(url, stream=True)
    if r.status_code != 200: return "", r.status_code
    buf = b""
    for ch in r.iter_content(1 << 16):
        buf += ch
        if len(buf) > cap: return "", "too_big"
    if not buf.startswith(b"%PDF"): return "", "not_pdf"
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(buf); f.flush()
        out = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=300).stdout
    return re.sub(r"[ \t]+", " ", out.decode("utf-8", "replace")).strip(), 200

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); a = ap.parse_args()
    st = SafeStager(CC, NAME, chunk=200, log=log); dd = DedupSkip(CC, NAME)
    items, start = [], 0
    while True:
        j = get(f"{BASE}/api/acts/async?draw=1&start={start}&length=200").json()
        d = j.get("data") or []
        items += d; start += len(d)
        if not d or start >= j.get("recordsFiltered", 0): break
    log.info("catalog %d acts", len(items))
    n = fail = short = 0
    for it in items:
        doc_id = f"act{it['id']}"
        if st.seen(doc_id) or doc_id in dd.skipped or not it.get("file_url"): continue
        url = BASE + quote(it["file_url"], safe="/()_-.,")
        if dd.check(doc_id, url, BASE + it["file_url"], url.replace("polis.bunge.go.tz", "polis.parliament.go.tz")): continue
        try: text, code = pdf_text(url)
        except Blocked as e: log.error("BLOCKED, stopping: %s", e); break
        except Exception as e: fail += 1; log.warning("fail %s %s", doc_id, e); continue
        if len(text) < 150: short += 1; log.info("no text %s (%s, %d chars; scanned?)", doc_id, code, len(text)); continue
        title = (it.get("title_en") or it.get("title_sw") or "").strip()
        lang = "sw" if re.search(r"\bSheria\b", text[:3000]) and not re.search(r"\bACT\b|\bAct\b", text[:3000]) else "en"
        rec = {"place_id": "iso:TZ", "country_code": "TZ", "doc_id": doc_id, "source_platform": "tz_bunge",
               "source_url": url, "doc_type": "gazette_act", "language": lang, "title_native": title or doc_id,
               "number": (f"Act {it.get('act_no')} of {it.get('posted')}" if it.get("act_no") else None),
               "adopted_date": (it.get("posted") if re.fullmatch(r"\d{4}", str(it.get("posted") or "")) else None),
               "consolidated": False, "content_format": "pdf_text", "text": text, "source_official": True,
               "source_org": "Parliament of the United Republic of Tanzania (Bunge)",
               "source_policy": "robots_allowed_rfc9309", "place_name": "Tanzania",
               "extra_metadata": {"title_sw": it.get("title_sw"), "title_en": it.get("title_en"),
                                  "bill_id": it.get("bill_id"), "tls_note": "server omits intermediate; verified with AIA-completed chain"}}
        if st.add(rec): n += 1
        if a.limit and n >= a.limit: break
    st.flush()
    log.info("DONE staged=%d dedup_skipped_now=%d fail=%d no_text=%d invalid=%d", n, dd.n, fail, short, st.bad)

if __name__ == "__main__":
    main()
