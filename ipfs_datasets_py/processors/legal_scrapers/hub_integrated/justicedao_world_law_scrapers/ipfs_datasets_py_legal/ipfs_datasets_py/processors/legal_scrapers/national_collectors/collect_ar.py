#!/usr/bin/env python3
"""Argentina: Constitución + leyes nacionales from official InfoLEG.

Official sources only:
  - InfoLEG (Ministerio de Justicia) http://www.infoleg.gob.ar
    https://servicios.infoleg.gob.ar/infolegInternet/
  - Open-data catalog (same ministry / SAIJ):
    https://datos.jus.gob.ar/dataset/base-de-datos-legislativos-infoleg
  - Boletín Oficial https://www.boletinoficial.gob.ar if needed for authentic text

National laws in force first (Constitución + tipo_norma=Ley). Not provincial.
Does not use La Ley, vLex, or other commercial databases. No WAF bypass.
archive_fallbacks.py on HTTP 429.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ar"
COUNTRY = "Argentina"
SOURCE_TYPE = "infoleg"
LICENSE = (
    "Official Argentine legislative texts (state documents) published by InfoLEG "
    "(Ministerio de Justicia de la Nación) and the Boletín Oficial. Creative Commons "
    "Attribution 4.0 on the InfoLEG open-data catalog (datos.jus.gob.ar). The Boletín "
    "Oficial / InfoLEG authentic text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.infoleg.gob.ar/"
INFOLEG = "https://servicios.infoleg.gob.ar/infolegInternet/"
CKAN = "https://datos.jus.gob.ar/api/3/action/package_show?id=base-de-datos-legislativos-infoleg"
CATALOG_ZIP = (
    "https://datos.jus.gob.ar/dataset/d9a963ea-8b1d-4ca3-9dd9-07a4773e8c23/"
    "resource/bf0ec116-ad4e-4572-a476-e57167a84403/download/base-infoleg-normativa-nacional.zip"
)
WORKERS = 4
SLEEP = 0.45
log = logging.getLogger("ar")

ART_ES = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[a-zA-Z])?(?:\s*(?:bis|ter|qu[aá]ter|quinquies))?)\b"
)
INEXISTENTE = re.compile(r"mostrarArchivoInexistente|no se (?:ha )?encontr", re.I)


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
    if len(docs) >= 2:
        return docs
    matches = list(ART_ES.finditer(text or ""))
    if len(matches) < 2:
        return []
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
            "metadata": {"text_extraction": {"source": "official", "backend": "infoleg_html"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def https(url: str) -> str:
    if not url:
        return url
    return url.replace("http://", "https://", 1)


def looks_like_law(text: str, html: str = "") -> bool:
    if not text or len(text) < 80:
        return False
    if INEXISTENTE.search(html or "") or INEXISTENTE.search(text[:800]):
        return False
    if af.is_challenge(html or text, 200):
        return False
    low = text.lower()
    if "archivo inexistente" in low or "no existe el archivo" in low:
        return False
    return True


def fetch_html(url: str) -> tuple[str, str, str]:
    url = https(url)
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        r = None
        log.info("live fail %s %s", url, exc)
    if r is not None:
        final = r.url or url
        limited = r.status_code == 429 or (r.content or b"")[:200].find(b"Service limit") >= 0
        if limited:
            wb = af.get_wayback_content(url)
            if wb.get("status") == "success":
                raw = wb.get("text") or ""
                if not raw and wb.get("content"):
                    raw = (wb["content"] or b"").decode("latin-1", "replace")
                if raw and looks_like_law(html_to_text(raw), raw):
                    return raw, wb.get("wayback_url") or url, "wayback"
            return "", url, "fail"
        if r.status_code in (404, 410):
            return "", url, "404"
        if r.status_code == 200 and r.content and len(r.content) > 200:
            html = r.content.decode(r.encoding or "latin-1", "replace")
            if "mostrarArchivoInexistente" in (final or "") or "mostrarArchivoInexistente" in html[:800]:
                return "", url, "missing"
            if looks_like_law(html_to_text(html), html):
                return html, final, "live"
    return "", url, "fail"


def catalog_csv_path() -> Path:
    return ROOT / CC / "raw" / "infoleg_csv" / "base-infoleg-normativa-nacional.csv"


def catalog_jsonl() -> Path:
    return ROOT / CC / "raw" / "catalog_leyes.jsonl"


def download_catalog() -> Path:
    csvp = catalog_csv_path()
    if csvp.exists() and csvp.stat().st_size > 1_000_000:
        return csvp
    zpath = ROOT / CC / "raw" / "base-infoleg-normativa-nacional.zip"
    if not zpath.exists() or zpath.stat().st_size < 1000:
        log.info("download InfoLEG catalog zip")
        r = http_get(CATALOG_ZIP, ua=UA, sleep=0.2, timeout=(20, 180), retries=5,
                     headers={"Accept": "application/zip, */*"})
        if r.status_code != 200 or not r.content or r.content[:2] != b"PK":
            raise RuntimeError(f"catalog zip HTTP {getattr(r, 'status_code', None)}")
        zpath.parent.mkdir(parents=True, exist_ok=True)
        zpath.write_bytes(r.content)
    dest = csvp.parent
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(dest)
    if not csvp.exists():
        # whatever name was inside
        for p in dest.glob("*.csv"):
            return p
    return csvp


def parse_catalog(csvp: Path) -> list[dict]:
    items: list[dict] = []
    seen = set()
    with csvp.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tipo = (row.get("tipo_norma") or "").strip()
            tl = tipo.lower()
            if tl not in {"ley", "decreto/ley", "decreto ley"}:
                continue
            nid = (row.get("id_norma") or "").strip()
            if not nid or nid in seen:
                continue
            orig = (row.get("texto_original") or "").strip()
            act = (row.get("texto_actualizado") or "").strip()
            if not orig and not act:
                continue
            seen.add(nid)
            num = (row.get("numero_norma") or "").strip()
            title = (row.get("titulo_sumario") or row.get("titulo_resumido") or "").strip()
            short = (row.get("titulo_resumido") or "").strip()
            if short and title and short.lower() not in title.lower():
                title = f"{short} — {title}"
            elif short and not title:
                title = short
            ident = f"ley-{num}-{nid}" if num else f"norma-{nid}"
            is_cn = nid == "804" or (num in {"24430", "24.430"} and "constituc" in (title or "").lower())
            items.append({
                "id": nid,
                "numero": num,
                "tipo": tipo,
                "title": title or f"{tipo} {num}".strip(),
                "ident": "cn-1994" if is_cn else ident,
                "texto_original": orig,
                "texto_actualizado": act,
                "fecha_sancion": row.get("fecha_sancion") or "",
                "fecha_boletin": row.get("fecha_boletin") or "",
                "organismo": row.get("organismo_origen") or "",
                "is_constitution": is_cn,
                "priority": 0 if is_cn else (1 if act else (2 if tl == "ley" else 3)),
            })
    items.sort(key=lambda x: (x["priority"], int(x["id"] or 0)))
    return items


def discover() -> list[dict]:
    jp = catalog_jsonl()
    if jp.exists() and jp.stat().st_size > 1000:
        items = []
        with jp.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog n=%s", len(items))
            return items
    csvp = download_catalog()
    items = parse_catalog(csvp)
    atomic_write(jp, "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))
    log.info("discovered leyes with text URLs n=%s", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or it.get("id")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    urls = []
    for u in (it.get("texto_actualizado"), it.get("texto_original")):
        u = (u or "").strip()
        if u and u not in urls:
            urls.append(u)
    html = ""
    used = ""
    method = "fail"
    for u in urls:
        html, used, method = fetch_html(u)
        if html:
            break
    if not html:
        log_failure(CC, {"identifier": ident, "source_url": urls[0] if urls else "",
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    text = html_to_text(html)
    if not looks_like_law(text, html):
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "not_law_text"})
        return "fail"
    date = iso_date(it.get("fecha_sancion") or it.get("fecha_boletin"))
    title = it.get("title") or ident
    if it.get("is_constitution"):
        title = "Constitución de la Nación Argentina"
        doc_type = "constitution"
    else:
        doc_type = "statute"
    docs = split_es(text, rid, used, date)
    official = f"{it.get('tipo') or 'Ley'} {it.get('numero') or it.get('id')}".strip()
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ar.py",
        eli=None, date=date, official_identifier=official,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {"method": "datos_jus_infoleg_csv", "id_norma": it.get("id"),
                          "seed_url": CATALOG_ZIP},
            "official_metadata": {
                "id_norma": it.get("id"),
                "numero_norma": it.get("numero"),
                "tipo_norma": it.get("tipo"),
                "organismo_origen": it.get("organismo"),
                "fecha_boletin": it.get("fecha_boletin"),
                "texto_actualizado": it.get("texto_actualizado") or None,
                "texto_original": it.get("texto_original") or None,
                "fetch_method": method,
            },
        },
        extra_fields={
            "canonical_title": title,
            "publication_date": iso_date(it.get("fecha_boletin")),
            "information_url": f"{INFOLEG}verNorma.do?id={it.get('id')}",
            "canonical_document_url": https(it.get("texto_actualizado") or it.get("texto_original") or used),
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
        "https://www.infoleg.gob.ar/",
        "https://servicios.infoleg.gob.ar/infolegInternet/",
        "https://datos.jus.gob.ar/dataset/base-de-datos-legislativos-infoleg",
        "https://www.boletinoficial.gob.ar/",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str, extra: str = ""):
        notes = (
            f"National Constitución + leyes (tipo_norma=Ley) then Decreto/Ley from the "
            f"official InfoLEG open-data catalog ({len(items)} rows with a text URL; "
            f"full catalog has ~27,613 Ley + ~2,462 Decreto/Ley). Rows without digital "
            f"text URLs are a documented ceiling. Provincial law excluded (catalog is "
            f"national BO first section). Prefer texto_actualizado, else texto_original. "
            f"Boletín Oficial / InfoLEG prevails. Started {t0}.{extra}"
        )
        write_summary(
            CC, country=COUNTRY,
            source="InfoLEG (Ministerio de Justicia) / datos.jus.gob.ar",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=ok, skipped=skip, failed=fail,
            coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 50 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_progress("catalog-backed incomplete")
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
