#!/usr/bin/env python3
"""Finland: Finlex open-data Akoma Ntoso statute-consolidated."""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "fi"
COUNTRY = "Finland"
SOURCE_TYPE = "finlex"
LICENSE = (
    "Finlex open data: reuse under the terms published at https://www.finlex.fi/en/open-data "
    "(Ministry of Justice open data service; Akoma Ntoso). Official statute texts are public."
)
UA = DEFAULT_UA + " source=https://opendata.finlex.fi/"
BASE = "https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute-consolidated"
NS = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}
log = logging.getLogger("fi")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def akn_text(el: ET.Element) -> str:
    parts = []
    def walk(e):
        tag = localtag(e.tag)
        if tag in {"meta", "identification", "references", "classification", "proprietary", "presentation", "workflow", "analysis"}:
            return
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            walk(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())
        if tag in {"p", "article", "chapter", "section", "subsection", "paragraph"}:
            parts.append("\n")
    walk(el)
    t = " ".join(parts)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def parse_acts(xml: str) -> list[dict]:
    xml = xml.strip()
    if not xml.startswith("<"):
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        xml2 = "<wrapper>" + xml + "</wrapper>"
        try:
            root = ET.fromstring(xml2)
        except ET.ParseError:
            return []
    acts = []
    for akn in root.iter():
        if localtag(akn.tag) != "akomaNtoso":
            continue
        act = None
        for child in list(akn):
            if localtag(child.tag) in {"act", "doc", "document"}:
                act = child
                break
        if act is None:
            continue
        lang = "fi"
        eli = None
        year = num = None
        title = ""
        date = None
        for el in act.iter():
            tag = localtag(el.tag)
            if tag == "FRBRalias" and el.get("name") == "eli":
                eli = el.get("value")
            if tag == "FRBRdate" and not date:
                date = iso_date(el.get("date"))
            if tag == "FRBRnumber":
                num = el.get("value")
            if tag == "FRBRlanguage":
                lang = (el.get("language") or "fi").lower()[:2]
            if tag == "docTitle" and not title:
                title = "".join(el.itertext()).strip()
            if tag == "shortTitle" and not title:
                title = "".join(el.itertext()).strip()
            if tag == "FRBRuri" and el.get("value"):
                m = re.search(r"/(\d{4})/(\d+)", el.get("value"))
                if m:
                    year, num = m.group(1), m.group(2)
        # language of this expression
        for el in act.iter():
            if localtag(el.tag) == "FRBRthis" and el.get("value"):
                if "/swe@" in el.get("value"):
                    lang = "sv"
                elif "/fin@" in el.get("value"):
                    lang = "fi"
        text = akn_text(act)
        if not text:
            continue
        ident = f"{year}-{num}" if year and num else (eli or title)[:80]
        acts.append({
            "ident": ident, "title": title or ident, "text": text, "eli": eli,
            "date": date, "lang": lang, "year": year, "num": num,
        })
    return acts


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    discovered = ok = skip = fail = 0
    # Finnish statutes historically from 1809/1917; Finlex consolidations typically 1980s-present plus older still in force
    years = list(range(1860, 2027))
    for year in years:
        page = 1
        prev_keys = None
        year_n = 0
        while page <= 400:
            r = http_get(f"{BASE}/{year}", ua=UA, sleep=0.2, params={"page": page, "limit": 10})
            if r.status_code != 200 or not r.content or b"<akomaNtoso" not in r.content:
                break
            batch = parse_acts(r.text)
            if not batch:
                break
            keys = tuple(sorted((a["ident"], a["lang"]) for a in batch))
            if keys == prev_keys:
                break
            prev_keys = keys
            by_key = {}
            for a in batch:
                by_key[(a["year"], a["num"], a["lang"])] = a
            for a in by_key.values():
                discovered += 1
                ident = f"{a['ident']}-{a['lang']}"
                rid = slug_id(CC, ident)
                if rid in done:
                    skip += 1
                    continue
                eli = a["eli"]
                source_url = eli or f"https://www.finlex.fi/fi/laki/ajantasa/{a['year']}/{a['num']}"
                rec = base_record(
                    cc=CC, country=COUNTRY, language=a["lang"], ident=ident, title=a["title"], text=a["text"],
                    source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
                    collector="fi-finlex-akn", eli=eli, date=a["date"],
                    official_identifier=f"{a['num']}/{a['year']}" if a["num"] else ident,
                    document_type="statute", law_status="current", is_current=True,
                    extra_meta={"discovery": {"method": "finlex_akn_year", "year": a["year"], "page": page}},
                )
                rec["languages"] = ["fi", "sv"]
                write_instrument(CC, rec)
                done.add(rid)
                ok += 1
                year_n += 1
            page += 1
        if year_n or year % 20 == 0:
            log.info("year %s new=%s ok=%s page=%s", year, year_n, ok, page)
        if year % 10 == 0:
            write_summary(CC, country=COUNTRY, source="Finlex open data (statute-consolidated AKN)",
                          source_urls=["https://opendata.finlex.fi/", "https://www.finlex.fi/en/open-data"],
                          license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                          coverage="catalog-backed incomplete", notes="paginated year dumps limit=10", last_run=utcnow())
    coverage = "full" if fail == 0 and discovered > 2000 else "catalog-backed incomplete"
    write_summary(CC, country=COUNTRY, source="Finlex open data (statute-consolidated Akoma Ntoso)",
                  source_urls=["https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute-consolidated",
                               "https://www.finlex.fi/en/open-data"],
                  license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                  coverage=coverage, notes="In-force consolidations (ajantasa) from official Finlex REST API, Finnish and Swedish expressions.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", discovered, ok, skip, fail)


if __name__ == "__main__":
    main()
