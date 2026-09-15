#!/usr/bin/env python3
"""Austria: RIS Bundesrecht konsolidiert via OGD API."""
from __future__ import annotations

import json
import time
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "at"
COUNTRY = "Austria"
SOURCE_TYPE = "ris_bundesrecht"
LICENSE = (
    "Austrian official legal texts are official works (amtliche Werke) and not "
    "protected by copyright (UrhG § 2 Abs. 1 Z 8 / § 7). RIS is Open Government Data "
    "(data.bka.gv.at / data.gv.at). Consolidations are informational."
)
UA = DEFAULT_UA + " source=https://data.bka.gv.at/ris/api/v2.6/"
API = "https://data.bka.gv.at/ris/api/v2.6/Bundesrecht"
log = logging.getLogger("at")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def parse_hits(data: dict) -> tuple[int, list[dict]]:
    ogd = (data or {}).get("OgdSearchResult") or {}
    res = ogd.get("OgdDocumentResults") or {}
    hits = res.get("Hits") or {}
    total = int(hits.get("#text") or 0)
    refs = res.get("OgdDocumentReference") or []
    if isinstance(refs, dict):
        refs = [refs]
    out = []
    for ref in refs:
        meta = ((ref.get("Data") or {}).get("Metadaten") or {})
        br = (meta.get("Bundesrecht") or {})
        kons = br.get("BrKons") or {}
        urls = []
        dl = (ref.get("Data") or {}).get("Dokumentliste") or {}
        cr = dl.get("ContentReference") or {}
        if isinstance(cr, dict):
            cr = [cr]
        for c in cr or []:
            for u in (((c.get("Urls") or {}).get("ContentUrl")) or []):
                if isinstance(u, dict):
                    urls.append(u)
        out.append({
            "gesetzesnummer": kons.get("Gesetzesnummer"),
            "kurztitel": (br.get("Kurztitel") or "").strip(),
            "titel": re.sub(r"<[^>]+>", " ", br.get("Titel") or "").strip(),
            "eli": br.get("Eli"),
            "typ": kons.get("Typ"),
            "dokumenttyp": kons.get("Dokumenttyp"),
            "inkraft": kons.get("Inkrafttretensdatum"),
            "ausserkraft": kons.get("Ausserkrafttretensdatum"),
            "gesamt_url": kons.get("GesamteRechtsvorschriftUrl"),
            "dokument_url": (meta.get("Allgemein") or {}).get("DokumentUrl"),
            "urls": urls,
            "para": kons.get("ArtikelParagraphAnlage"),
        })
    return total, out


def discover() -> dict:
    """Unique Gesetzesnummer -> metadata for in-force federal instruments."""
    catp = ROOT / CC / "raw" / "laws.json"
    if catp.exists() and catp.stat().st_size > 1000:
        return json.loads(catp.read_text(encoding="utf-8"))
    laws = {}
    page = 1
    total = None
    while page <= 5000:
        s = get_session(UA)
        try:
            time.sleep(0.2)
            r = s.post(API, data={
                "Applikation": "BrKons",
                "DokumenteProSeite": "OneHundred",
                "Seitennummer": str(page),
            }, headers={"Accept": "application/json", "User-Agent": UA}, timeout=(20, 90))
        except Exception as exc:
            log.info("page %s err %s", page, exc)
            break
        if r.status_code != 200:
            log.info("page %s status %s", page, r.status_code)
            break
        try:
            data = r.json()
        except Exception:
            break
        total, refs = parse_hits(data)
        if not refs:
            break
        for ref in refs:
            gn = ref.get("gesetzesnummer")
            if not gn:
                continue
            prev = laws.get(gn)
            if prev is None or (ref.get("para") in ("§ 0", "§0", "0") and prev.get("para") not in ("§ 0", "§0", "0")):
                laws[gn] = ref
        log.info("page=%s got=%s unique=%s total_hits=%s", page, len(refs), len(laws), total)
        if total and page * 100 >= int(total):
            break
        page += 1
    catp.write_text(json.dumps(laws, ensure_ascii=False, indent=2), encoding="utf-8")
    return laws


def fetch_text(law: dict) -> tuple[str, str]:
    # Prefer XML then HTML of entire instrument
    xml_url = None
    for u in law.get("urls") or []:
        dt = (u.get("DataType") or u.get("dataType") or "").lower()
        url = u.get("#text") or u.get("Url") or u.get("url")
        if not url:
            continue
        if dt == "xml" or str(url).endswith(".xml"):
            xml_url = url
            break
    if xml_url:
        r = http_get(xml_url, ua=UA, sleep=0.3)
        if r.status_code == 200 and r.content and b"<" in r.content[:80]:
            return xml_to_text(r.text), xml_url
    url = law.get("gesamt_url") or law.get("dokument_url")
    if url:
        r = http_get(url, ua=UA, sleep=0.35)
        if r.status_code == 200 and r.content:
            return html_to_text(r.text), url
    gn = law.get("gesetzesnummer")
    fallback = f"https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer={gn}"
    r = http_get(fallback, ua=UA, sleep=0.35)
    if r.status_code == 200:
        return html_to_text(r.text), fallback
    return "", fallback


def main():
    setup()
    t0 = utcnow()
    laws = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for gn, law in laws.items():
        ident = f"bgbl-{gn}"
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        text, src = fetch_text(law)
        if not text or len(text) < 40:
            fail += 1
            log_failure(CC, {"identifier": gn, "source_url": src, "status": "failed", "reason": "empty_text"})
            continue
        aus = law.get("ausserkraft") or ""
        if aus and aus < "2026-09-02":
            status, cur = "repealed", False
        else:
            status, cur = "current", True
        title = law.get("kurztitel") or law.get("titel") or gn
        rec = base_record(
            cc=CC, country=COUNTRY, language="de", ident=ident, title=title, text=text,
            source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="at-ris-ogd",
            eli=law.get("eli"), date=iso_date(law.get("inkraft")),
            official_identifier=gn, document_type=law.get("typ") or "statute",
            law_status=status, is_current=cur,
            extra_meta={"discovery": {"method": "ris_ogd_bundesrecht", "gesetzesnummer": gn}},
            extra_fields={"valid_from": iso_date(law.get("inkraft")), "valid_to": iso_date(law.get("ausserkraft"))},
        )
        write_instrument(CC, rec)
        ok += 1
        if (ok + fail) % 100 == 0:
            log.info("ok=%s fail=%s skip=%s / %s", ok, fail, skip, len(laws))
            write_summary(CC, country=COUNTRY, source="RIS Bundesrecht konsolidiert (OGD API)",
                          source_urls=["https://data.bka.gv.at/ris/api/v2.6/", "https://www.ris.bka.gv.at/"],
                          license_text=LICENSE, discovered=len(laws), fetched=ok, skipped=skip, failed=fail,
                          coverage="catalog-backed incomplete", notes="unique Gesetzesnummer", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="RIS Bundesrecht konsolidiert (OGD API)",
                  source_urls=["https://data.bka.gv.at/ris/api/v2.6/", "https://www.ris.bka.gv.at/"],
                  license_text=LICENSE, discovered=len(laws), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if fail == 0 else "catalog-backed incomplete",
                  notes="Federal consolidated law grouped by Gesetzesnummer from RIS OGD. Types BG/BVG/V/K/Vertrag.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s skip=%s fail=%s disc=%s", ok, skip, fail, len(laws))


if __name__ == "__main__":
    main()
