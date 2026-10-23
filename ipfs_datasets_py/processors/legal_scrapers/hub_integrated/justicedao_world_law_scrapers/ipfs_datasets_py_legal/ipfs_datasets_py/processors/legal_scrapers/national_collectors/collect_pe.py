#!/usr/bin/env python3
"""Peru: Constitución + leyes from official El Peruano / SPIJ / Congreso.

Official sources only:
  - El Peruano / Editora Perú open data (Diario Oficial PDF links)
    https://www.datosabiertos.gob.pe/dataset/dispositivos-legales
    https://busquedas.elperuano.pe
  - SPIJ https://spij.minjus.gob.pe  https://spijweb.minjus.gob.pe
  - Congreso Archivo Digital https://www.leyes.congreso.gob.pe
    Constitución edición oficial:
    https://www3.congreso.gob.pe/Docs/constitucion/constitucion/Constitucion-web_2026.pdf

Constitución + leyes (not every decreto). El Peruano authentic text prevails.
No vLex / La Ley / Lexis. No WAF bypass.
archive_fallbacks.py on HTTP 429 of official URLs.
SPIJ live TLS often fails from this host; Wayback of official SPIJ/Congreso URLs
is used only as a fallback.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "pe"
COUNTRY = "Peru"
SOURCE_TYPE = "el_peruano_congreso"
LICENSE = (
    "Official Peruvian legislative texts published in the Diario Oficial El "
    "Peruano and by the Congreso de la República / SPIJ (MINJUSDH). El Peruano "
    "authentic text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://busquedas.elperuano.pe/"
CKAN = "https://www.datosabiertos.gob.pe/api/3/action/package_show?id=dispositivos-legales"
CONST_PDF = "https://www3.congreso.gob.pe/Docs/constitucion/constitucion/Constitucion-web_2026.pdf"
CONGRESO = "https://www.leyes.congreso.gob.pe/"
SPIJ = "https://spij.minjus.gob.pe/"
SPIJWEB = "https://spijweb.minjus.gob.pe/"
ELPERUANO = "https://busquedas.elperuano.pe/"
WORKERS = 3
SLEEP = 0.4
MIN_TEXT = 80
MAX_PDF = 40 * 1024 * 1024
log = logging.getLogger("pe")

ART_ES = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[A-Za-z])?(?:\s*(?:bis|ter|qu[aá]ter|quinquies))?)\b"
)
LEY_TIPO = re.compile(r"^\s*ley(\s|$|n[°ºo.]|es\b)", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=120,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_es(text: str, law_id: str, source_url: str, date: Optional[str], backend: str) -> list[dict]:
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
            "metadata": {"text_extraction": {"source": "official", "backend": backend}},
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


def is_ley_tipo(tipo: str) -> bool:
    t = (tipo or "").strip().lower()
    if not t:
        return False
    if any(x in t for x in ("decreto", "resolu", "acuerdo", "directiva", "ordenanza",
                            "edicto", "sentencia", "casacion", "aviso")):
        return False
    return bool(LEY_TIPO.match(t)) or t in {"ley", "leyes"}


def fetch_bytes(url: str, accept: str = "*/*") -> tuple[bytes, str, str, int]:
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                     headers={"Accept": accept})
    except Exception as exc:
        log.info("live fail %s %s", url, exc)
        r = None
    if r is not None:
        if r.status_code == 429:
            wb = af.get_wayback_content(url)
            if wb.get("status") == "success":
                content = wb.get("content") or b""
                if not content and wb.get("text"):
                    content = wb["text"].encode("utf-8", "replace")
                return content, wb.get("wayback_url") or url, "wayback", 200
            return b"", url, "fail", 429
        if r.status_code in (404, 410):
            return b"", url, "404", r.status_code
        if r.status_code == 200 and r.content:
            return r.content, r.url or url, "live", 200
        return b"", url, "fail", r.status_code or 0
    return b"", url, "fail", 0


def ckan_package() -> dict:
    body, used, method, status = fetch_bytes(CKAN, "application/json")
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return {}
    result = data.get("result") or {}
    if isinstance(result, list):
        result = result[0] if result else {}
    return result if isinstance(result, dict) else {}


def pick_csv_resources(pkg: dict) -> list[dict]:
    res = pkg.get("resources") or []
    yearly = []
    monthly = []
    for r in res:
        url = (r.get("url") or "").strip()
        name = (r.get("name") or "").strip()
        if not url or not url.lower().endswith(".csv"):
            continue
        # prefer multi-month / yearly files over overlapping monthlies
        m = re.search(r"Periodo_(\d{8})_(\d{8})", url, re.I)
        if not m:
            yearly.append(r)
            continue
        a, b = m.group(1), m.group(2)
        span = (int(b[:4]) - int(a[:4])) * 12 + (int(b[4:6]) - int(a[4:6]))
        rec = dict(r)
        rec["_span"] = span
        rec["_start"] = a
        rec["_end"] = b
        if span >= 2:
            yearly.append(rec)
        else:
            monthly.append(rec)
    # yearly/range first; monthlies only to cover dates after last yearly end
    yearly.sort(key=lambda x: (x.get("_start") or "", x.get("_end") or ""))
    chosen = []
    covered_end = ""
    for r in yearly:
        end = r.get("_end") or ""
        start = r.get("_start") or ""
        if covered_end and start <= covered_end:
            # overlap: keep the longer span already chosen
            continue
        chosen.append(r)
        if end > covered_end:
            covered_end = end
    for r in sorted(monthly, key=lambda x: x.get("_start") or ""):
        start = r.get("_start") or ""
        end = r.get("_end") or ""
        if covered_end and start <= covered_end:
            continue
        chosen.append(r)
        if end > covered_end:
            covered_end = end
    log.info("ckan csv chosen %s (from %s resources)", len(chosen), len(res))
    return chosen


def parse_csv_bytes(raw: bytes, source_csv: str) -> list[dict]:
    text = None
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if not text:
        return []
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except Exception:
        dialect = csv.excel
    f = io.StringIO(text)
    rows = []
    reader = csv.DictReader(f, dialect=dialect)
    for row in reader:
        norm = {re.sub(r"\s+", "_", (k or "").strip().upper()): (v or "").strip() for k, v in row.items()}
        tipo = norm.get("DISPOSITIVO") or norm.get("TIPO") or norm.get("TIPO_DISPOSITIVO") or ""
        if not is_ley_tipo(tipo):
            continue
        link = norm.get("LINK") or norm.get("URL") or norm.get("ARCHIVO") or ""
        if link and not link.lower().startswith("http"):
            link = urljoin(ELPERUANO, link)
        num = norm.get("NUMERO") or norm.get("NRO") or ""
        fecha = norm.get("FECHA_PUBLICACION") or norm.get("FECHA") or ""
        sumilla = norm.get("SUMILLA") or norm.get("TITULO") or ""
        entidad = norm.get("ENTIDAD") or ""
        if not link and not num:
            continue
        ident = f"ley-{re.sub(r'[^0-9A-Za-z]+', '-', num).strip('-') or 'na'}-{fecha or 'nd'}"
        rows.append({
            "ident": ident[:160],
            "numero": num,
            "tipo": tipo,
            "title": sumilla or f"Ley {num}",
            "fecha": fecha,
            "entidad": entidad,
            "url": link,
            "kind": "ley",
            "source_csv": source_csv,
            "priority": 1,
        })
    return rows


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 50:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: dict[str, dict] = {}

    def add(it: dict):
        key = it.get("ident") or it.get("url")
        if not key:
            return
        prev = items.get(key)
        if prev and prev.get("priority", 9) <= it.get("priority", 9):
            return
        items[key] = it

    add({
        "ident": "cn-1993",
        "title": "Constitución Política del Perú",
        "url": CONST_PDF,
        "kind": "constitution",
        "numero": "1993",
        "fecha": "1993-12-29",
        "priority": 0,
    })
    pkg = ckan_package()
    for res in pick_csv_resources(pkg):
        url = res.get("url") or ""
        log.info("download catalog csv %s", url)
        raw, used, method, status = fetch_bytes(url, "text/csv, */*")
        if not raw or len(raw) < 200:
            log.info("csv fail %s method=%s status=%s", url, method, status)
            continue
        dest = ROOT / CC / "raw" / Path(url.split("?")[0]).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        for it in parse_csv_bytes(raw, url):
            add(it)
        log.info("after %s catalog n=%s", dest.name, len(items))
    out = list(items.values())
    out.sort(key=lambda x: (x.get("priority", 9), x.get("fecha") or "", x.get("numero") or ""))
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in out))
    log.info("discovered n=%s", len(out))
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or it.get("url")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it.get("url") or ""
    raw, used, method, status = fetch_bytes(url, "application/pdf, text/html, */*")
    if not raw:
        log_failure(CC, {"identifier": ident, "source_url": url,
                         "status": "failed", "reason": f"empty_{status}"})
        return "fail"
    text = ""
    backend = "html"
    if raw[:4] == b"%PDF":
        if len(raw) > MAX_PDF:
            log_failure(CC, {"identifier": ident, "source_url": used,
                             "status": "failed", "reason": "pdf_too_large"})
            return "fail"
        text = pdf_to_text(raw)
        backend = "pdftotext"
    else:
        html = raw.decode("utf-8", "replace")
        if af.is_challenge(html, 200):
            log_failure(CC, {"identifier": ident, "source_url": used,
                             "status": "failed", "reason": "challenge"})
            return "fail"
        text = html_to_text(html)
        backend = "html"
    if not text or len(text) < MIN_TEXT:
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    date = iso_date(it.get("fecha"))
    title = it.get("title") or ident
    is_cn = it.get("kind") == "constitution" or "constituci" in title.lower()
    if is_cn:
        title = "Constitución Política del Perú"
        doc_type = "constitution"
        official = "Constitución Política 1993"
        ident = "cn-1993"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
    else:
        doc_type = "statute"
        official = f"Ley {it.get('numero')}".strip() if it.get("numero") else ident
        if title and official.lower() not in title.lower():
            title = f"{official} — {title}"
    docs = split_es(text, rid, used, date, backend)
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_pe.py",
        eli=url,
        date=date, official_identifier=official,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": {"method": method},
            "discovery": {"method": "datosabiertos_elperuano_csv" if not is_cn else "congreso_pdf",
                          "seed_url": CKAN if not is_cn else CONST_PDF},
            "official_metadata": {
                "numero": it.get("numero"),
                "tipo": it.get("tipo"),
                "entidad": it.get("entidad"),
                "source_csv": it.get("source_csv"),
                "fetch_method": method,
                "text_backend": backend,
            },
        },
        extra_fields={
            "canonical_title": title,
            "publication_date": date,
            "information_url": url,
            "canonical_document_url": url,
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
        CONST_PDF,
        CONGRESO,
        SPIJ,
        SPIJWEB,
        ELPERUANO,
        "https://www.datosabiertos.gob.pe/dataset/dispositivos-legales",
        "https://www3.congreso.gob.pe/constitucionyreglamento/",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str):
        notes = (
            f"Constitución Política 1993 (Congreso edición oficial PDF 2026) plus "
            f"leyes (tipo DISPOSITIVO=Ley) from Editora Perú / El Peruano open-data "
            f"CSVs on datosabiertos.gob.pe ({len(items)} catalog rows). Decretos and "
            f"resoluciones excluded. SPIJ live TLS failed from this host; Congreso "
            f"Archivo Digital timed out — pre-2013 leyes not in the open-data CSVs "
            f"are a documented ceiling. El Peruano prevails. Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="El Peruano / Congreso de la República / SPIJ (MINJUSDH)",
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
