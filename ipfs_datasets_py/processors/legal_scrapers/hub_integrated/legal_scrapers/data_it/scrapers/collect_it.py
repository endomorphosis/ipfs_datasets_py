#!/usr/bin/env python3
"""Italy: Normattiva OpenData ricerca/avanzata + dettaglio-atto (official BFF)."""
from __future__ import annotations
import json, logging, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "it", "Italy", "normattiva"
LICENSE = (
    "Normattiva OpenData (dati.normattiva.it). Official Italian legislation. "
    "Reuse per Normattiva OpenData terms. HTML from official dettaglio-atto API; "
    "Akoma Ntoso via caricaAKN when present."
)
UA = DEFAULT_UA + " source=https://dati.normattiva.it/"
API = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"
log = logging.getLogger("it")
HDR = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def api_post(path: str, payload: dict, retries: int = 4):
    last = None
    for attempt in range(1, retries + 1):
        try:
            time.sleep(0.35)
            r = get_session(UA).post(API + path, json=payload, timeout=(20, 90), headers=HDR)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(30, 2 ** attempt))
                last = r
                continue
            return r
        except Exception as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    if isinstance(last, Exception):
        raise last
    return last


def discover() -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 500:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            key = (row.get("dataGU"), row.get("codiceRedazionale"))
            if key[1] and key not in seen:
                seen.add(key); items.append(row)
        if items:
            log.info("resume catalog %s", len(items))
            return items
    # Republic-era full years; Kingdom years sampled via same loop (empty years skip quickly)
    for year in range(1861, 2027):
        page = 1
        pages = 1
        while page <= pages and page <= 400:
            payload = {
                "dataInizioEmanazione": f"{year}-01-01",
                "dataFineEmanazione": f"{year}-12-31",
                "orderType": "vecchio",
                "paginazione": {"paginaCorrente": page, "numeroElementiPerPagina": 50},
            }
            try:
                r = api_post("/api/v1/ricerca/avanzata", payload)
            except Exception as exc:
                log.info("search %s p%s err %s", year, page, exc)
                break
            if r.status_code != 200:
                log.info("search %s p%s HTTP %s %s", year, page, r.status_code, r.text[:160])
                break
            try:
                data = r.json()
            except Exception:
                break
            rows = data.get("listaAtti") or []
            found = int(data.get("numeroAttiTrovati") or 0)
            pages = int(data.get("numeroPagine") or 1) or 1
            for row in rows:
                key = (row.get("dataGU"), row.get("codiceRedazionale"))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                rec = {
                    "dataGU": row.get("dataGU"),
                    "codiceRedazionale": row.get("codiceRedazionale"),
                    "titoloAtto": row.get("titoloAtto"),
                    "denominazioneAtto": row.get("denominazioneAtto"),
                    "numeroAtto": row.get("numeroAtto"),
                    "annoProvvedimento": row.get("annoProvvedimento"),
                    "dataEmanazione": row.get("dataEmanazione"),
                    "numeroGU": row.get("numeroGU"),
                }
                items.append(rec)
                append_catalog(CC, rec)
            log.info("year %s p%s/%s got=%s total_items=%s found=%s", year, page, pages, len(rows), len(items), found)
            if not rows:
                break
            page += 1
    return items


def fetch_text(row: dict) -> tuple[str, str, str]:
    data_gu = str(row.get("dataGU") or "")
    codice = str(row.get("codiceRedazionale") or "")
    title = (row.get("titoloAtto") or "").strip("[] ").strip()
    src = f"https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={data_gu}&codiceRedazionale={codice}"
    r = api_post("/api/v1/atto/dettaglio-atto", {
        "dataGU": data_gu, "codiceRedazionale": codice, "formatoRichiesta": "V",
    })
    if r.status_code == 200 and r.content:
        try:
            data = r.json()
        except Exception:
            data = {}
        atto = ((data.get("data") or {}).get("atto")) or data.get("atto") or {}
        html = atto.get("articoloHtml") or atto.get("html") or ""
        if atto.get("titolo"):
            title = atto.get("titolo")
        if html:
            return html_to_text(html), src, title
    # official AKN export fallback
    dgu = data_gu.replace("-", "")
    akn = f"https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={codice}&dataVigenza=20260902"
    rr = http_get(akn, ua=UA, sleep=0.4)
    if rr.status_code == 200 and rr.content and (b"<akoma" in rr.content[:500].lower() or b"<?xml" in rr.content[:40]):
        return xml_to_text(rr.text), akn, title
    return "", src, title


def fetch_one(row: dict, done: set[str]) -> str:
    data_gu = str(row.get("dataGU") or "")
    codice = str(row.get("codiceRedazionale") or "")
    ident = f"{data_gu}-{codice}" if codice else json.dumps(row)[:40]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text, src, title = fetch_text(row)
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": src, "status": "failed", "reason": "empty_text"})
        return "fail"
    dtype = (row.get("denominazioneAtto") or "statute").lower()
    rec = base_record(
        cc=CC, country=COUNTRY, language="it", ident=ident, title=title or ident, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="it-normattiva-opendata",
        eli=None, date=iso_date(data_gu or row.get("dataEmanazione")),
        official_identifier=ident, document_type=dtype, law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "ricerca_avanzata", "codiceRedazionale": codice,
                                  "denominazioneAtto": row.get("denominazioneAtto")}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    notes = "Official OpenAPI paths: POST /api/v1/ricerca/avanzata (catalog) and POST /api/v1/atto/dettaglio-atto (HTML). The old /api/v1/ricerca path 404s."
    if not items:
        write_summary(CC, country=COUNTRY, source="Normattiva OpenData",
                      source_urls=["https://www.normattiva.it/", "https://dati.normattiva.it/", API],
                      license_text=LICENSE, discovered=0, fetched=0, skipped=0, failed=0,
                      coverage="catalog-backed incomplete",
                      notes="ricerca/avanzata returned no rows this run. " + notes, last_run=utcnow())
        return
    with ThreadPoolExecutor(max_workers=3) as ex:
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
            if n % 80 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(items), ok, fail)
                write_summary(CC, country=COUNTRY, source="Normattiva OpenData API",
                              source_urls=["https://www.normattiva.it/", "https://dati.normattiva.it/"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes=notes, last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Normattiva OpenData (Poligrafico) official BFF",
                  source_urls=["https://www.normattiva.it/", "https://dati.normattiva.it/",
                               API + "/api/v1/ricerca/avanzata", API + "/api/v1/atto/dettaglio-atto"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if items and fail == 0 else "catalog-backed incomplete",
                  notes=notes + " Catalog is year-paged emanazione dates 1861–2026.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
