#!/usr/bin/env python3
"""Costa Rica: Constitución + leyes from official SCIJ / SINALEVI (PGR).

Official sources only:
  - SINALEVI / SCIJ (Procuraduría General de la República)
    https://sinalevi.go.cr
    https://pgrweb.go.cr  http://www.pgrweb.go.cr
    https://www.pgr.go.cr  Sistema Costarricense de Información Jurídica
  - Official AJAX: POST /ResultadosNormativa/_CargarTextoCompleto
    (idFichaNorma, version) — same records as nrm_texto_completo.aspx
  - La Gaceta authentic text prevails.

Constitución + leyes (not every decreto). No vLex / La Ley / Lexis.
No WAF bypass. archive_fallbacks.py on HTTP 429 of official URLs.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "cr"
COUNTRY = "Costa Rica"
SOURCE_TYPE = "sinalevi_scij"
LICENSE = (
    "Official Costa Rican legislative texts published by the Procuraduría "
    "General de la República (SINALEVI / Sistema Costarricense de Información "
    "Jurídica). La Gaceta authentic text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://sinalevi.go.cr/"
SINAL = "https://sinalevi.go.cr"
PGRWEB = "https://pgrweb.go.cr"
SEARCH = f"{SINAL}/BusquedaSimple/Resultados"
TEXT_API = f"{SINAL}/ResultadosNormativa/_CargarTextoCompleto"
FICHA_API = f"{SINAL}/ResultadosNormativa/_CargarFicha"
CONST_FICHA = 871
CONST_VERSION = 147492
TIPO_CONST = "1"
TIPO_LEY = "8"
WORKERS = 3
SLEEP = 0.4
MIN_TEXT = 80
log = logging.getLogger("cr")

ART_ES = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[A-Za-z])?(?:\s*(?:bis|ter|qu[aá]ter|quinquies|sexies))?)\b"
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def split_es(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    matches = list(ART_ES.finditer(text or ""))
    if len(matches) < 2:
        return docs if len(docs) >= 2 else []
    out = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": doc_id, "title": heading, "text": chunk, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "sinalevi_html"}},
        })
        if len(out) >= 4000:
            break
    if len(out) > len(docs):
        return out
    return docs if len(docs) >= 2 else out


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog_leyes.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 200:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def extract_search_json(html: str) -> list[dict]:
    i = html.find('[{"IdFichaNorma":')
    if i < 0:
        return []
    try:
        arr, _ = json.JSONDecoder().raw_decode(html[i:])
    except Exception:
        return []
    return arr if isinstance(arr, list) else []


def search_sinalevi(*, text: str, tipo: str, year: str = "", limit: str = "-1") -> list[dict]:
    data = {
        "textBuscar": text,
        "textAnnio": year,
        "TipoNorma": tipo,
        "opcionSelected": "1",
        "selectedBuscarEn": "F",
        "cantidadResultados": limit,
        "pagina": "1",
        "radioBtnGroup": "1",
    }
    try:
        r = get_session(UA).post(
            SEARCH, data=data, timeout=(20, 90),
            headers={"User-Agent": UA, "Accept": "text/html, */*",
                     "Referer": f"{SINAL}/Escritorio/BusquedaSimple"},
        )
    except Exception as exc:
        log.info("search fail tipo=%s year=%s %s", tipo, year, exc)
        return []
    if r.status_code == 429:
        log.info("search 429 tipo=%s year=%s", tipo, year)
        time_mod = __import__("time")
        time_mod.sleep(8)
        return []
    if r.status_code != 200 or not r.content:
        log.info("search HTTP %s tipo=%s year=%s", r.status_code, tipo, year)
        return []
    return extract_search_json(r.text)


def row_to_item(row: dict, kind: str) -> dict:
    ficha = row.get("IdFichaNorma")
    ver = row.get("IdVersionNorma")
    num = row.get("NumeroNormativa")
    title = (row.get("NombreNormativa") or "").strip()
    fecha = row.get("stringFechaNormativa") or row.get("FechaNormativa") or ""
    ident = f"cn-1949" if kind == "constitution" else f"ley-{num}-{ficha}"
    return {
        "ident": ident,
        "ficha": ficha,
        "version": ver,
        "numero": str(num) if num is not None else "",
        "title": title,
        "fecha": fecha,
        "kind": kind,
        "ente": (row.get("DescEnteEmisor") or "").strip(),
        "tipo": (row.get("NombreTipoNorma") or "").strip(),
        "url": f"{SINAL}/ResultadosNormativa/Informacion?param1={ficha}&param2={ver}&param3=1",
        "scij_url": (
            f"{PGRWEB}/scij/Busqueda/Normativa/Normas/nrm_texto_completo.aspx"
            f"?nValor1=1&nValor2={ficha}&nValor3={ver}&param1=NRTC&strTipM=TC"
        ),
        "priority": 0 if kind == "constitution" else 1,
    }


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 200:
        log.info("resume catalog n=%s", len(existing))
        return existing
    by_ficha: dict[str, dict] = {}

    def add(it: dict):
        key = str(it.get("ficha") or "")
        if not key:
            return
        prev = by_ficha.get(key)
        if prev and prev.get("priority", 9) <= it.get("priority", 9):
            if it.get("title") and not prev.get("title"):
                prev["title"] = it["title"]
            return
        by_ficha[key] = it

    add({
        "ident": "cn-1949",
        "ficha": CONST_FICHA,
        "version": CONST_VERSION,
        "numero": "0",
        "title": "Constitución Política de la República de Costa Rica",
        "fecha": "07/11/1949",
        "kind": "constitution",
        "url": f"{SINAL}/ResultadosNormativa/Informacion?param1={CONST_FICHA}&param2={CONST_VERSION}&param3=1",
        "scij_url": (
            f"{PGRWEB}/scij/Busqueda/Normativa/Normas/nrm_texto_completo.aspx"
            f"?nValor1=1&nValor2={CONST_FICHA}&nValor3={CONST_VERSION}&param1=NRTC&strTipM=TC"
        ),
        "priority": 0,
    })
    for row in search_sinalevi(text="Constitucion", tipo=TIPO_CONST, limit="-1"):
        add(row_to_item(row, "constitution"))
    # Global ficha search for Ley, then year slices if the unscoped query is capped.
    global_rows = search_sinalevi(text="de", tipo=TIPO_LEY, limit="-1")
    log.info("global leyes 'de' n=%s", len(global_rows))
    for row in global_rows:
        add(row_to_item(row, "ley"))
    extra = search_sinalevi(text="Ley", tipo=TIPO_LEY, limit="-1")
    log.info("global leyes 'Ley' n=%s", len(extra))
    for row in extra:
        add(row_to_item(row, "ley"))
    if sum(1 for v in by_ficha.values() if v.get("kind") == "ley") < 1500:
        for year in range(1949, 2027):
            rows = search_sinalevi(text="de", tipo=TIPO_LEY, year=str(year), limit="-1")
            for row in rows:
                add(row_to_item(row, "ley"))
            if year % 10 == 0:
                log.info("year %s running leyes=%s", year, sum(1 for v in by_ficha.values() if v.get("kind") == "ley"))
            __import__("time").sleep(0.25)
    out = list(by_ficha.values())
    out.sort(key=lambda x: (x.get("priority", 9), int(re.sub(r"\D", "", str(x.get("numero") or "0")) or 0)))
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in out))
    log.info("discovered n=%s (constitution + leyes)", len(out))
    return out


def post_json(url: str, data: dict) -> tuple[Optional[dict], str, str]:
    scij = data.get("_scij_url") or ""
    payload = {k: v for k, v in data.items() if not str(k).startswith("_")}
    try:
        if SLEEP:
            __import__("time").sleep(SLEEP)
        r = get_session(UA).post(
            url, data=payload, timeout=(20, 90),
            headers={"User-Agent": UA, "Accept": "application/json, */*",
                     "X-Requested-With": "XMLHttpRequest", "Referer": SINAL + "/"},
        )
    except Exception as exc:
        log.info("live post fail %s %s", url, exc)
        r = None
    if r is not None:
        if r.status_code == 429:
            # 429 of the official AJAX URL — Wayback of the equivalent SCIJ HTML.
            if scij:
                wb = af.get_wayback_content(scij)
                if wb.get("status") == "success":
                    raw = wb.get("text") or ""
                    if raw and not af.is_challenge(raw, 200):
                        return {"html": raw}, wb.get("wayback_url") or scij, "wayback"
            return None, url, "fail"
        if r.status_code in (404, 410):
            return None, url, "404"
        if r.status_code == 200 and r.content:
            try:
                payload = r.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get("html"):
                return payload, r.url or url, "live"
    return None, url, "fail"


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or f"ficha-{it.get('ficha')}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    ficha = it.get("ficha")
    ver = it.get("version") or -1
    scij = it.get("scij_url") or ""
    payload, used, method = post_json(
        TEXT_API,
        {"idFichaNorma": ficha, "version": ver, "busqueda": "", "_scij_url": scij},
    )
    html = (payload or {}).get("html") or ""
    if not html and scij:
        # live AJAX empty: try official SCIJ HTML (may redirect to SINALEVI shell)
        try:
            r = http_get(scij, ua=UA, sleep=SLEEP, timeout=(20, 60), retries=2,
                         headers={"Accept": "text/html, */*"})
        except Exception:
            r = None
        if r is not None and r.status_code == 429:
            wb = af.get_wayback_content(scij)
            if wb.get("status") == "success":
                html = wb.get("text") or ""
                used = wb.get("wayback_url") or scij
                method = "wayback"
        elif r is not None and r.status_code == 200 and r.content and "sinalevi.go.cr" not in (r.url or ""):
            html = r.content.decode(r.encoding or "utf-8", "replace")
            used = r.url or scij
            method = "live"
    if not html or len(html) < 200:
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "empty_html"})
        return "fail"
    if af.is_challenge(html, 200):
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "challenge"})
        return "fail"
    text = html_to_text(html)
    if not text or len(text) < MIN_TEXT:
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    date = iso_date(it.get("fecha"))
    title = it.get("title") or ident
    is_cn = it.get("kind") == "constitution" or "constituci" in title.lower()
    if is_cn:
        title = "Constitución Política de la República de Costa Rica"
        doc_type = "constitution"
        official = "Constitución Política 1949"
        ident = "cn-1949"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
    else:
        doc_type = "statute"
        official = f"Ley {it.get('numero')}".strip()
        if title and official.lower() not in title.lower():
            title = f"{official} — {title}"
    docs = split_es(text, rid, used, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_cr.py",
        eli=it.get("url"),
        date=date, official_identifier=official,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": {"method": method},
            "discovery": {"method": "sinalevi_busqueda_simple", "ficha": ficha,
                          "version": ver, "seed_url": SEARCH},
            "official_metadata": {
                "IdFichaNorma": ficha,
                "IdVersionNorma": ver,
                "NumeroNormativa": it.get("numero"),
                "NombreTipoNorma": it.get("tipo") or ("Constitución Política" if is_cn else "Ley"),
                "ente_emisor": it.get("ente"),
                "fetch_method": method,
            },
        },
        extra_fields={
            "canonical_title": title,
            "information_url": it.get("url"),
            "canonical_document_url": it.get("url"),
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    source_urls = [
        "https://sinalevi.go.cr/",
        "https://pgrweb.go.cr/",
        "http://www.pgrweb.go.cr/scij/Busqueda/Normativa/Normas/nrm_libre.aspx",
        "https://www.pgr.go.cr/servicios/sinalevi/",
        TEXT_API,
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str):
        notes = (
            f"Constitución Política 1949 (IdFichaNorma {CONST_FICHA}) plus leyes "
            f"from official SINALEVI Búsqueda Simple (TipoNorma=Ley). Catalog "
            f"{len(items)} rows. Texts via POST /ResultadosNormativa/_CargarTextoCompleto "
            f"(official PGR AJAX, same corpus as SCIJ nrm_texto_completo). Decretos "
            f"ejecutivos excluded. La Gaceta prevails. Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="SINALEVI / SCIJ (Procuraduría General de la República)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=ok, skipped=skip, failed=fail,
            coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
        )

    rest = []
    for it in items:
        if it.get("kind") == "constitution":
            try:
                st = fetch_one(it, done)
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"id": "cn", "status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            log.info("constitution %s", st)
        else:
            rest.append(it)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in rest]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 25 == 0 or n == len(rest):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(rest), ok, skip, fail)
                write_progress("catalog-backed incomplete")
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
