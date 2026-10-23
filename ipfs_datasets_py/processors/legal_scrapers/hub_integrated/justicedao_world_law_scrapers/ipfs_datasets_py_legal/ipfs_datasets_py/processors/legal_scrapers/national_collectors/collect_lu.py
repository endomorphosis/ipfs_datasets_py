#!/usr/bin/env python3
"""Luxembourg: Casemates RDF (content negotiation) + filestore HTML/XML. SPARQL is an Angular SPA."""
from __future__ import annotations
import json, logging, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "lu", "Luxembourg", "legilux"
LICENSE = (
    "data.legilux.public.lu texts and metadata: Creative Commons Attribution 4.0 "
    "(CC BY 4.0) as stated at https://data.legilux.public.lu/home/intro"
)
UA = DEFAULT_UA + " source=https://data.legilux.public.lu/"
DATA = "http://data.legilux.public.lu"
log = logging.getLogger("lu")
RDF_ACCEPT = "application/rdf+xml"


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def rdf_get(url: str) -> str:
    r = http_get(url, ua=UA, sleep=0.3, retries=2, headers={"Accept": RDF_ACCEPT})
    if r.status_code == 200 and b"<rdf" in r.content[:200].lower():
        return r.text
    return ""


def rdf_uris(xml: str) -> list[str]:
    uris = re.findall(r"https?://data\.legilux\.public\.lu/eli/etat/leg/(?:loi|rgd|arl|agd|argd|dec|code|memorial)/[^\"'<\s]+", xml)
    out = []
    seen = set()
    for u in uris:
        u = u.split("#")[0].rstrip("/")
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def discover() -> list[str]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    elis, seen = [], set()
    if catp.exists() and catp.stat().st_size > 500:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            e = row.get("eli")
            if e and e not in seen:
                seen.add(e); elis.append(e)
        if elis:
            log.info("resume catalog %s", len(elis))
            return elis
    # Snowball from known ELI works first (SPARQL is an Angular SPA).
    seeds = [
        f"{DATA}/eli/etat/leg/code/penal",
        f"{DATA}/eli/etat/leg/code/civil",
        f"{DATA}/eli/etat/leg/code/travail",
        f"{DATA}/eli/etat/leg/code/commerce",
        f"{DATA}/eli/etat/leg/code/procedure_penale",
        f"{DATA}/eli/etat/leg/loi/2009/07/10/n2/jo",
        f"{DATA}/eli/etat/leg/loi/1868/10/17/n1/jo",
        f"{DATA}/eli/etat/leg/loi/1879/06/18/n1/jo",
    ]
    queue = list(seeds)
    hops = 0
    while queue and len(elis) < 6000 and hops < 4000:
        u = queue.pop(0); hops += 1
        xml = rdf_get(u)
        if not xml:
            continue
        if "/jo" in u and u.rstrip("/").endswith("jo") and u not in seen:
            seen.add(u); elis.append(u); append_catalog(CC, {"eli": u})
        for v in rdf_uris(xml):
            if v in seen:
                continue
            if v.endswith("/jo"):
                seen.add(v); elis.append(v); append_catalog(CC, {"eli": v}); queue.append(v)
            elif "/eli/etat/leg/" in v:
                queue.append(v)
        if hops % 20 == 0:
            log.info("snowball hops=%s catalog=%s queue=%s", hops, len(elis), len(queue))
    log.info("after snowball catalog=%s", len(elis))
    # Enumerate recent Mémorial A issues via RDF
    for year in range(1945, 2027):
        misses = 0
        for n in range(1, 400):
            url = f"{DATA}/eli/etat/leg/memorial/{year}/a{n}"
            xml = rdf_get(url)
            if not xml or "<rdf:Description" not in xml:
                misses += 1
                if misses >= 6:
                    break
                continue
            misses = 0
            found = 0
            for u in rdf_uris(xml):
                if "/memorial/" in u:
                    continue
                if not u.endswith("/jo"):
                    if re.search(r"/(loi|rgd|arl|agd|argd|dec|code)/.+/n\d+$", u):
                        u = u + "/jo"
                    else:
                        continue
                if u not in seen:
                    seen.add(u); elis.append(u); append_catalog(CC, {"eli": u, "memorial": url}); found += 1
            # memorial RDF is often metadata-only; also try following HTML? skip
            if n % 20 == 0:
                log.info("memorial %s a%s catalog=%s (+%s this)", year, n, len(elis), found)
        log.info("year %s catalog=%s", year, len(elis))
    return elis


def fetch_one(eli: str, done: set[str]) -> str:
    ident = eli.split("/eli/", 1)[-1]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    xml = rdf_get(eli)
    title = ident
    html_url = xml_url = ""
    if xml:
        m = re.search(r"<jolux:title>([^<]+)</jolux:title>", xml)
        if m:
            title = html.unescape(m.group(1)).strip()
        for m in re.finditer(r'jolux:isExemplifiedBy rdf:resource="([^"]+)"', xml):
            u = m.group(1)
            if u.endswith(".xml") or "/xml/" in u:
                xml_url = u
            elif u.endswith(".html") or "/html/" in u:
                html_url = u
    text = ""; src = eli
    for url in (xml_url, html_url):
        if not url:
            continue
        r = http_get(url, ua=UA, sleep=0.35, retries=2,
                     headers={"Accept": "application/xml, text/html, application/akn+xml, */*"})
        if r.status_code != 200 or not r.content or len(r.content) < 80:
            continue
        if b"<?xml" in r.content[:40] or b"<akoma" in r.content[:400].lower():
            text = xml_to_text(r.text); src = url; break
        if b"<html" in r.content[:200].lower() or b"<!doctype" in r.content[:40].lower():
            text = html_to_text(r.text); src = url; break
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": eli, "status": "failed", "reason": "empty_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="fr", ident=ident, title=title, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="lu-legilux-rdf",
        eli=eli.replace("http://", "https://"), date=None, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "casemates_rdf"}},
    )
    rec["languages"] = ["fr", "de"]
    write_instrument(CC, rec)
    return "ok"


def main():
    import html
    globals()["html"] = html
    setup(); t0 = utcnow()
    elis = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fetch_one, e, done) for e in elis]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 80 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(elis), ok, fail)
                write_summary(CC, country=COUNTRY, source="Legilux Casemates RDF",
                              source_urls=["https://data.legilux.public.lu/", "https://legilux.public.lu/"],
                              license_text=LICENSE, discovered=len(elis), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="RDF content-negotiation; SPARQL is SPA", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Legilux Casemates RDF + filestore (CC BY 4.0)",
                  source_urls=["https://data.legilux.public.lu/home/intro", "https://legilux.public.lu/"],
                  license_text=LICENSE, discovered=len(elis), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if elis and fail == 0 else "catalog-backed incomplete",
                  notes="SPARQL endpoint returns Angular app-root (documented). Catalog via RDF GET of Mémorial A issues + snowball cites. Texts from filestore HTML/XML (Akoma Ntoso).",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(elis), ok, fail)


if __name__ == "__main__":
    main()
