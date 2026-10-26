#!/usr/bin/env python3
"""Estonia: Riigi Teataja official search API + public-api blob-xml."""
from __future__ import annotations
import json, logging, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "ee", "Estonia", "riigiteataja"
LICENSE = (
    "Riigi Teataja texts are official public information (avalik teave). "
    "https://www.riigiteataja.ee/"
)
UA = DEFAULT_UA + " source=https://www.riigiteataja.ee/"
BASE = "https://www.riigiteataja.ee"
SEARCH = f"{BASE}/api/oigusakt_otsing/1/otsi"
log = logging.getLogger("ee")
TODAY = "2026-09-02"
DOCTYPES = ("seadus", "määrus")  # national consolidated; exclude KOV via kov=false


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def discover() -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 500:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            gid = str(row.get("globaalID") or "")
            if gid and gid not in seen:
                seen.add(gid); items.append(row)
        if items:
            log.info("resume catalog %s", len(items))
            return items
    for dok in DOCTYPES:
        page = 1
        while page <= 400:
            r = http_get(SEARCH, ua=UA, sleep=0.25, retries=3,
                         headers={"Accept": "application/json"},
                         params={
                             "leht": page, "limiit": 50, "dokument": dok,
                             "kehtiv": TODAY, "kehtivKehtetus": "false",
                             "mitteJoustunud": "false", "kov": "false",
                         })
            if r.status_code != 200:
                log.info("search %s p%s HTTP %s", dok, page, r.status_code)
                break
            try:
                data = r.json()
            except Exception:
                break
            rows = data.get("aktid") or []
            meta = data.get("metaandmed") or {}
            if not rows:
                break
            for row in rows:
                gid = str(row.get("globaalID") or "")
                if not gid or gid in seen:
                    continue
                seen.add(gid)
                rec = {
                    "globaalID": gid,
                    "terviktekstID": row.get("terviktekstID"),
                    "pealkiri": row.get("pealkiri"),
                    "lyhend": row.get("lyhend"),
                    "liik": row.get("liik") or dok,
                    "valjaandja": row.get("valjaandja"),
                    "url": row.get("url"),
                    "kehtivus": row.get("kehtivus"),
                    "staatus": row.get("staatus"),
                }
                items.append(rec)
                append_catalog(CC, rec)
            log.info("search %s p%s got=%s total=%s kokku=%s", dok, page, len(rows), len(items), meta.get("kokku"))
            kokku = int(meta.get("kokku") or 0)
            if page * 50 >= kokku:
                break
            page += 1
    return items


def fetch_one(row: dict, done: set[str]) -> str:
    gid = str(row["globaalID"])
    ident = f"akt-{gid}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    xml = http_get(f"{BASE}/public-api/api/v1/akt/{gid}/blob-xml", ua=UA, sleep=0.3, retries=3,
                   headers={"Accept": "application/xml, application/octet-stream, */*"})
    text = ""
    src = f"{BASE}/akt/{gid}"
    if xml.status_code == 200 and xml.content and b"<" in xml.content[:120]:
        text = xml_to_text(xml.text)
        src = f"{BASE}/public-api/api/v1/akt/{gid}/blob-xml"
    if not text or len(text) < 40:
        htmlr = http_get(f"{BASE}/public-api/api/v1/akt/{gid}/blob-html", ua=UA, sleep=0.3, retries=2)
        if htmlr.status_code == 200 and htmlr.content:
            text = html_to_text(htmlr.text)
            src = f"{BASE}/public-api/api/v1/akt/{gid}/blob-html"
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": src, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = row.get("pealkiri") or ident
    keht = row.get("kehtivus") or {}
    date = iso_date((keht or {}).get("algus") if isinstance(keht, dict) else None)
    rec = base_record(
        cc=CC, country=COUNTRY, language="et", ident=ident, title=title, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="ee-riigiteataja-api",
        eli=f"{BASE}/eli/{gid}", date=date, official_identifier=row.get("lyhend") or ident,
        document_type=row.get("liik") or "statute", law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "oigusakt_otsing", "globaalID": gid, "valjaandja": row.get("valjaandja")}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 50 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(items), ok, fail)
                write_summary(CC, country=COUNTRY, source="Riigi Teataja public API",
                              source_urls=["https://www.riigiteataja.ee/", "https://www.riigiteataja.ee/api/oigusakt_otsing/1/otsi"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="seadus+määrus in-force kov=false", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Riigi Teataja (Estonian State Gazette) official API",
                  source_urls=["https://www.riigiteataja.ee/",
                               "https://www.riigiteataja.ee/api/oigusakt_otsing/1/otsi",
                               "https://www.riigiteataja.ee/public-api/api/v1/akt/"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if items and fail == 0 else "catalog-backed incomplete",
                  notes="In-force national seadus and määrus (kov=false, kehtivKehtetus=false, mitteJoustunud=false) via oigusakt_otsing + blob-xml.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
