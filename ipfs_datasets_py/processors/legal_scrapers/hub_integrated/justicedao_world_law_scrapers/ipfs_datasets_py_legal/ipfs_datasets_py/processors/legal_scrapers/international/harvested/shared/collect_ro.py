#!/usr/bin/env python3
"""Romania: official Portal Legislativ SOAP API (http FreeWebService.svc/SOAP)."""
from __future__ import annotations
import logging, re, sys, time
from xml.etree import ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "ro", "Romania", "legislatie_just"
LICENSE = "legislatie.just.ro official Portal Legislativ of the Ministry of Justice (SOAP FreeWebService)."
UA = DEFAULT_UA + " source=http://legislatie.just.ro/apiws"
SOAP = "http://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"
NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "t": "http://tempuri.org/",
    "a": "http://schemas.datacontract.org/2004/07/FreeWebService",
}
log = logging.getLogger("ro")
_token = {"v": None, "t": 0.0}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def soap(action: str, body_inner: str, timeout=(15, 60)) -> ET.Element:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<s:Body>{body_inner}</s:Body></s:Envelope>"
    )
    last = None
    for attempt in range(1, 5):
        try:
            time.sleep(0.4)
            r = get_session(UA).post(
                SOAP, data=envelope.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"http://tempuri.org/IFreeWebService/{action}"',
                    "User-Agent": UA,
                },
                timeout=timeout,
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(20, 2 ** attempt)); last = r; continue
            if r.status_code != 200:
                raise RuntimeError(f"SOAP HTTP {r.status_code} {r.text[:180]}")
            return ET.fromstring(r.content)
        except Exception as exc:
            last = exc
            time.sleep(min(12, 1.5 * attempt))
    raise RuntimeError(f"SOAP {action} failed: {last}")


def get_token(force: bool = False) -> str:
    if not force and _token["v"] and (time.time() - _token["t"]) < 600:
        return _token["v"]
    root = soap("GetToken", '<GetToken xmlns="http://tempuri.org/"/>', timeout=(15, 30))
    el = root.find(".//{http://tempuri.org/}GetTokenResult")
    if el is None or not (el.text or "").strip():
        raise RuntimeError("empty token")
    _token["v"] = el.text.strip()
    _token["t"] = time.time()
    return _token["v"]


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def search_page(year: int, page: int, token: str) -> list[dict]:
    inner = (
        '<Search xmlns="http://tempuri.org/">'
        '<SearchModel xmlns:q="http://schemas.datacontract.org/2004/07/FreeWebService">'
        f"<q:NumarPagina>{page}</q:NumarPagina>"
        "<q:RezultatePagina>10</q:RezultatePagina>"
        f"<q:SearchAn>{year}</q:SearchAn>"
        "</SearchModel>"
        f"<tokenKey>{token}</tokenKey>"
        "</Search>"
    )
    root = soap("Search", inner, timeout=(15, 90))
    out = []
    for legi in root.iter("{http://schemas.datacontract.org/2004/07/FreeWebService}Legi"):
        rec = {}
        for child in list(legi):
            rec[local(child.tag)] = (child.text or "").strip()
        out.append(rec)
    return out


def discover_and_fetch() -> tuple[int, int, int, int]:
    import os
    done = existing_ids(CC)
    discovered = ok = skip = fail = 0
    token = get_token()
    max_new = int(os.environ.get("MAX_NEW", "0") or 0)
    max_seconds = int(os.environ.get("MAX_SECONDS", "0") or 0)
    t_start = time.time()
    # Official SOAP Search by year. Homepage TCP-closes; SOAP /SOAP works over HTTP.
    y_hi=int(os.environ.get("YEAR_START","2026") or 2026)
    y_lo=int(os.environ.get("YEAR_END","1990") or 1990)
    for year in range(y_hi, y_lo-1, -1):
        page = 0
        empty_pages = 0
        while page < 400:
            try:
                rows = search_page(year, page, token)
            except Exception as exc:
                log.info("search fail year=%s p=%s %s — refresh token", year, page, exc)
                try:
                    token = get_token(force=True)
                    rows = search_page(year, page, token)
                except Exception as exc2:
                    log.info("search abort year=%s p=%s %s", year, page, exc2)
                    break
            if not rows:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                page += 1
                continue
            empty_pages = 0
            for rec in rows:
                discovered += 1
                append_catalog(CC, {k: rec.get(k) for k in ("Numar", "Titlu", "TipAct", "DataVigoare", "LinkHtml", "Emitent")})
                link = rec.get("LinkHtml") or ""
                num = rec.get("Numar") or ""
                tip = rec.get("TipAct") or ""
                did = ""
                m = re.search(r"DetaliiDocument/(\d+)", link)
                if m:
                    did = m.group(1)
                ident = did or f"{year}-{tip}-{num}"
                rid = slug_id(CC, ident)
                if rid in done:
                    skip += 1
                    continue
                text = rec.get("Text") or ""
                text = html_to_text(text) if "<" in text else text
                text = re.sub(r"\s+\n", "\n", text).strip()
                if len(text) < 80:
                    log_failure(CC, {"identifier": ident, "source_url": link, "status": "failed", "reason": "empty_text"})
                    fail += 1
                    continue
                title = rec.get("Titlu") or f"{tip} {num}/{year}".strip()
                inst = base_record(
                    cc=CC, country=COUNTRY, language="ro", ident=ident, title=title, text=text,
                    source_url=link or f"http://legislatie.just.ro/Public/DetaliiDocument/{ident}",
                    source_type=SOURCE_TYPE, license_text=LICENSE, collector="ro-just-soap",
                    eli=None, date=rec.get("DataVigoare") or None,
                    official_identifier=title[:180], document_type=(tip or "statute").lower(),
                    law_status="current", is_current=True,
                    extra_meta={"discovery": {"method": "just_soap_search", "emitent": rec.get("Emitent"),
                                              "publicatie": rec.get("Publicatie"), "numar": num}},
                )
                write_instrument(CC, inst)
                done.add(rid)
                ok += 1
                if max_new and ok >= max_new:
                    log.info("MAX_NEW=%s reached", max_new)
                    return discovered, ok, skip, fail
                if max_seconds and (time.time() - t_start) > max_seconds:
                    log.info("MAX_SECONDS reached")
                    return discovered, ok, skip, fail
            log.info("year %s p%s n=%s disc=%s ok=%s fail=%s", year, page, len(rows), discovered, ok, fail)
            if ok and ok % 40 == 0:
                write_summary(CC, country=COUNTRY, source="legislatie.just.ro SOAP FreeWebService",
                              source_urls=["http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl",
                                           "http://legislatie.just.ro/serviciulweblegislatie.htm",
                                           "https://legislatie.just.ro/"],
                              license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete",
                              notes="Official SOAP Search (GetToken+Search). HTML portal TCP-closes; HTTP SOAP /SOAP works.",
                              last_run=utcnow())
            if len(rows) < 10:
                break
            page += 1
        log.info("year %s done disc=%s ok=%s", year, discovered, ok)
    return discovered, ok, skip, fail


def main():
    setup(); t0 = utcnow()
    try:
        discovered, ok, skip, fail = discover_and_fetch()
        notes = (
            "Official Ministry of Justice SOAP API (GetToken + Search by year). "
            "HTML portal at legislatie.just.ro TCP-closes from this network; "
            "http://legislatie.just.ro/apiws/FreeWebService.svc/SOAP works. "
            "SearchResult Legi.Text is the official act body (may be truncated with … on very long acts)."
        )
    except Exception as exc:
        log.exception("collector failed")
        discovered = ok = skip = 0
        fail = 1
        notes = f"SOAP collector failed: {exc}. HTML portal still TCP-closes."
    write_summary(CC, country=COUNTRY, source="legislatie.just.ro SOAP FreeWebService",
                  source_urls=["http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl",
                               "http://legislatie.just.ro/serviciulweblegislatie.htm",
                               "https://legislatie.just.ro/"],
                  license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete" if ok else "catalog-backed incomplete",
                  notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", discovered, ok, fail)


if __name__ == "__main__":
    main()
