#!/usr/bin/env python3
"""Turkey (TR): national legislation from the official Mevzuat Bilgi Sistemi (www.mevzuat.gov.tr), live.
Listing: POST /Anasayfa/MevzuatDatatable (the portal's own DataTables endpoint, read-only search).
Text:    GET  /anasayfa/MevzuatFihristDetayIframe?MevzuatTur=..&MevzuatNo=..&MevzuatTertip=..  (HTML text).
robots.txt (RFC 9309, common/robots.py) checked for every request; >=3 s between requests.
Dedup: docs whose mevzuat URL is already in an older ipfs_*_laws repo are skipped (common/newcc.DedupSkip).
Resumable: staging/national/_work/TR/tr_mevzuat.done + catalog cache.  Usage: collect_tr_mevzuat.py [--limit N] [--types A,B]
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
import argparse, json, re, sys, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/national/common"))
from natlib import PoliteSession, Blocked, html_to_text, setup_log, STAGE  # noqa
from robots import robots_for, UA  # noqa
from newcc import DedupSkip, SafeStager  # noqa

CC, NAME = "TR", "tr_mevzuat"
BASE = "https://www.mevzuat.gov.tr"
TYPES = {  # form value -> doc_type
    "Kanun": "statute", "KHK": "statute", "CumhurbaskaniKararnameleri": "statute", "Tuzuk": "regulation",
    "CumhurbaskanligiYonetmelikleri": "regulation", "Yonetmelik": "regulation",
    "KurumVeKurulusYonetmeligi": "regulation", "UniversiteYonetmeligi": "regulation",
    "Teblig": "regulation", "IcTuzuk": "regulation", "CumhurbaskaniKararlari": "decision",
}
log = setup_log(CC, NAME)
S = PoliteSession(min_delay=3.0, log=log)

def post_list(tur, start, length=100):
    url = BASE + "/Anasayfa/MevzuatDatatable"
    rb, _ = robots_for(url)
    if not (rb.can_fetch(UA, url) and rb.can_fetch("*", url)): raise Blocked("robots " + url)
    body = {"draw": 1, "start": start, "length": length, "parameters": {
        "MevzuatTur": tur, "YonetmelikMevzuatTur": "OsmanliKanunu", "AranacakIfade": "", "AranacakYer": "Baslik",
        "MevzuatNo": "", "BaslangicTarihi": "", "BitisTarihi": ""}}
    for i in range(5):
        wait = S.min_delay - (time.time() - S.last.get("www.mevzuat.gov.tr", 0))
        if wait > 0: time.sleep(wait)
        S.last["www.mevzuat.gov.tr"] = time.time()
        try:
            r = S.s.post(url, data=json.dumps(body), timeout=90, headers={
                "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest"})
            if r.status_code == 200: return r.json()
            log.warning("list %s %s HTTP %s", tur, start, r.status_code)
            if r.status_code in (401, 403): raise Blocked(f"HTTP {r.status_code}")
        except (ValueError, Exception) as e:
            if isinstance(e, Blocked): raise
            log.warning("list err %s %s %s", tur, start, e)
        time.sleep(15 * (i + 1))
    raise RuntimeError(f"list failed {tur} {start}")

def catalog(types):
    cf = STAGE / "_work" / CC / f"{NAME}.catalog.{'-'.join(types)}.json"
    if cf.exists(): return json.loads(cf.read_text())
    items = []
    for t in types:
        start, total = 0, None
        while total is None or start < total:
            j = post_list(t, start)
            total = j.get("recordsFiltered") or 0
            data = j.get("data") or []
            if not data: break
            for d in data: d["_form_tur"] = t
            items += data; start += len(data)
            log.info("catalog %s %d/%d", t, start, total)
    tmp = cf.with_name(cf.name + ".tmp"); tmp.write_text(json.dumps(items, ensure_ascii=False)); tmp.rename(cf)
    return items

def dmy(s):
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s or "")
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--types", default=",".join(TYPES)); a = ap.parse_args()
    types = [t for t in a.types.split(",") if t in TYPES]
    items = catalog(types)
    log.info("catalog total %d", len(items))
    st = SafeStager(CC, NAME, chunk=200, log=log); dd = DedupSkip(CC, NAME)
    n = fail = short = 0
    for it in items:
        tur, no, tert = it.get("mevzuatTur"), it.get("mevzuatNo"), it.get("mevzuatTertip") or "5"
        doc_id = f"{tur}.{tert}.{no}"
        if st.seen(doc_id) or doc_id in dd.skipped: continue
        page = f"{BASE}/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tert}"
        if dd.check(doc_id, page, f"{BASE}/MevzuatMetin/{tur}.{tert}.{no}.pdf",
                    f"{BASE}/MevzuatMetin/{tur}.{tert}.{no}.doc"): continue
        src = f"{BASE}/anasayfa/MevzuatFihristDetayIframe?MevzuatTur={tur}&MevzuatNo={no}&MevzuatTertip={tert}"
        try:
            r = S.get(src)
        except Blocked as e:
            log.error("BLOCKED, stopping: %s", e); break
        except Exception as e:
            fail += 1; log.warning("fail %s %s", doc_id, e); continue
        if r.status_code != 200: fail += 1; log.warning("HTTP %s %s", r.status_code, doc_id); continue
        h = r.text
        body = re.search(r"(?is)<body[^>]*>(.*)</body>", h); body = body[1] if body else h
        text = html_to_text(body)
        if len(text) < 150:
            short += 1; log.info("no text (%d chars) %s", len(text), doc_id); continue
        rec = {"place_id": "iso:TR", "country_code": "TR", "doc_id": doc_id, "source_platform": "tr_mevzuat",
               "source_url": page, "doc_type": TYPES.get(it["_form_tur"], "regulation"), "language": "tr",
               "title_native": (it.get("mevAdi") or "").strip() or doc_id, "number": str(no),
               "adopted_date": dmy(it.get("kabulTarih")), "published_date": dmy(it.get("resmiGazeteTarihi")),
               "consolidated": True, "content_format": "html", "text": text,
               "source_official": True, "source_org": "T.C. Cumhurbaşkanlığı Mevzuat Bilgi Sistemi",
               "source_policy": "robots_allowed_rfc9309", "place_name": "Türkiye",
               "extra_metadata": {"mevzuat_tur": tur, "mevzuat_tur_name": it.get("mevzuatTurEnumString"),
                                  "tertip": tert, "resmi_gazete_sayisi": it.get("resmiGazeteSayisi"),
                                  "text_url": src}}
        if st.add(rec): n += 1
        if a.limit and n >= a.limit: break
    st.flush()
    log.info("DONE staged=%d dedup_skipped_now=%d fail=%d no_text=%d invalid=%d", n, dd.n, fail, short, st.bad)

if __name__ == "__main__":
    main()
