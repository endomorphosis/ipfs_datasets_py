#!/usr/bin/env python3
"""Uganda: Parliament of Uganda official act PDFs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ug", "Uganda", "en"
SOURCE_TYPE = "parliament_uganda"
LICENSE = "Parliament of Uganda (parliament.go.ug). Authentic text prevails. Not legal advice."
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.go.ug/)"
ART = re.compile(r"(?im)^\s*((?:Section|Article)\s+\d+[A-Za-z]?\.?)\b")
log = logging.getLogger("ug")

def discover():
    items, seen = [], set()
    for su in ["https://www.parliament.go.ug/documents/acts", "https://www.parliament.go.ug/documents", "https://www.parliament.go.ug/"]:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc); continue
        for href in re.findall(r'href="([^"]+\.pdf)"', r.text or "", re.I):
            url = urljoin(su, href)
            if url in seen: continue
            seen.add(url); items.append((Path(url).stem[:140], url))
    for prefix in ("www.parliament.go.ug/sites/default/files/", "parliament.go.ug/sites/default/files/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix", extra_filters=["mimetype:application/pdf"]):
            orig = (h.get("original") or "").replace("http://", "https://")
            if not orig or orig in seen or ".pdf" not in orig.lower(): continue
            seen.add(orig); items.append((Path(orig.split("?")[0]).stem[:140], orig))
    log.info("catalog %s", len(items)); return items

def main():
    setup_log(CC); t0 = utcnow(); max_new = env_int("MAX_NEW", 40); max_seconds = env_int("MAX_SECONDS", 2000)
    t_start = time.time(); done = existing_ids(CC); ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new: break
        if time.time() - t_start > max_seconds: break
        rid = slug_id(CC, ident)
        if rid in done: skip += 1; continue
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1; log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")}); continue
        title = next((ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18), ident)
        if save_instrument(cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ug.py", article_re=ART, extra_meta={"fetch_method": got.get("method")}):
            ok += 1; done.add(rid); log.info("ok %s chars=%s", ident[:60], len(text))
        else: fail += 1
    write_summary(CC, country=COUNTRY, source="Parliament of Uganda", source_urls=["https://www.parliament.go.ug/"], license_text=LICENSE, discovered=ok+skip+fail, fetched=ok, skipped=skip, failed=fail, coverage="acts/PDF catalog incomplete", notes="Official Parliament of Uganda PDFs. Not legal advice.", last_run=t0)
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)

if __name__ == "__main__":
    main()
