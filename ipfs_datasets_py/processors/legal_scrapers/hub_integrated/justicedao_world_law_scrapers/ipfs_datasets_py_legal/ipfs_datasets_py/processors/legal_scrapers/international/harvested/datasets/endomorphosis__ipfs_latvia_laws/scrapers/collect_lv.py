#!/usr/bin/env python3
"""Latvia: likumi.lv official consolidations via sitemap."""
from __future__ import annotations
import logging, re, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
CC, COUNTRY, SOURCE_TYPE = "lv", "Latvia", "likumi"
LICENSE = "Official consolidations of Latvijas Vēstnesis on likumi.lv; Law on Official Publications and Legal Information. Public reuse of official texts."
UA = DEFAULT_UA + " source=https://likumi.lv/"
log = logging.getLogger("lv")

def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])

def discover() -> list[str]:
    ids=[]
    r=http_get("https://likumi.lv/sitemap-index.xml", ua=UA, sleep=0.3)
    pages=re.findall(r"<loc>([^<]+)</loc>", r.text) if r.status_code==200 else []
    if not pages:
        pages=["https://likumi.lv/sitemap-1.xml","https://likumi.lv/sitemap-2.xml"]
    seen=set()
    for p in pages:
        pr=http_get(p, ua=UA, sleep=0.3)
        if pr.status_code!=200: continue
        for loc in re.findall(r"<loc>([^<]+)</loc>", pr.text):
            m=re.search(r"/ta/id/(\d+)", loc)
            if not m: continue
            if "grozijum" in loc: continue
            i=m.group(1)
            if i in seen: continue
            seen.add(i); ids.append(i)
            append_catalog(CC, {"id": i, "loc": loc})
        log.info("sitemap %s ids=%s", p, len(ids))
    return ids

def main():
    setup(); t0=utcnow()
    ids=discover(); done=existing_ids(CC); ok=skip=fail=0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def one(i):
        ident=i; rid=slug_id(CC, ident)
        if rid in done: return "skip"
        url=f"https://likumi.lv/ta/id/{i}"
        r=http_get(url, ua=UA, sleep=0.45)
        if r.status_code!=200 or not r.content:
            log_failure(CC, {"identifier": i, "source_url": url, "status": "failed", "reason": f"http_{r.status_code}"})
            return "fail"
        text=html_to_text(r.text)
        title=ident
        m=re.search(r"<title>([^<]+)</title>", r.text, re.I)
        if m: title=re.sub(r"\s+"," ", m.group(1)).strip()
        if not text or len(text)<40:
            log_failure(CC, {"identifier": i, "source_url": url, "status": "failed", "reason": "empty_text"})
            return "fail"
        rec=base_record(cc=CC, country=COUNTRY, language="lv", ident=ident, title=title, text=text,
                        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="lv-likumi",
                        eli=url, date=None, official_identifier=i, document_type="statute",
                        law_status="current", is_current=True)
        write_instrument(CC, rec); return "ok"
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs=[ex.submit(one,i) for i in ids]
        n=0
        for fut in as_completed(futs):
            n+=1
            try: st=fut.result()
            except Exception as exc:
                st="fail"; log_failure(CC, {"status":"failed","reason":repr(exc)})
            ok += st=="ok"; skip += st=="skip"; fail += st=="fail"
            if n%200==0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(ids), ok, fail)
                write_summary(CC, country=COUNTRY, source="likumi.lv",
                              source_urls=["https://likumi.lv/"], license_text=LICENSE,
                              discovered=len(ids), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="sitemap /ta/id", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="likumi.lv (Latvijas Vēstnesis consolidations)",
                  source_urls=["https://likumi.lv/", "https://likumi.lv/sitemap-index.xml"],
                  license_text=LICENSE, discovered=len(ids), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if fail==0 and ids else "catalog-backed incomplete",
                  notes="Consolidated acts from official sitemap; amendment-only URLs skipped. robots.txt respected (no /redakcijas-datums/).",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(ids), ok, fail)

if __name__ == "__main__":
    main()
