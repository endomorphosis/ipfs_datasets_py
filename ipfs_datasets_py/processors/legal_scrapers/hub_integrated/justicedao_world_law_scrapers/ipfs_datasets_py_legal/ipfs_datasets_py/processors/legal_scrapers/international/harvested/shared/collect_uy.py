#!/usr/bin/env python3
"""Uruguay: Constitución + leyes from official IMPO (Diario Oficial / Normativa).

Official sources only:
  - IMPO Centro de Información Oficial https://www.impo.com.uy
    Datos Abiertos JSON: append ?json=true to a public norma URL
    e.g. https://www.impo.com.uy/bases/constitucion/1967-1967?json=true
         https://www.impo.com.uy/bases/leyes/{nro}-{anio}?json=true
  - Diario Oficial authentic text prevails.

Constitución + leyes (not every decreto). No vLex / La Ley / Lexis.
No WAF bypass. archive_fallbacks.py on HTTP 429 of official IMPO URLs.
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

CC = "uy"
COUNTRY = "Uruguay"
SOURCE_TYPE = "impo"
LICENSE = (
    "Official Uruguayan legislative texts published by IMPO (Centro de "
    "Información Oficial). Reuse under IMPO / Datos Abiertos Uruguay terms. "
    "The Diario Oficial authentic text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.impo.com.uy/"
IMPO = "https://www.impo.com.uy"
CONST_URL = f"{IMPO}/bases/constitucion/1967-1967?json=true"
SCHEMA_URL = f"{IMPO}/resources/basesIMPO.json"
WORKERS = 3
SLEEP = 0.45
MIN_TEXT = 40
log = logging.getLogger("uy")

ART_ES = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[A-Za-z])?(?:\s*(?:bis|ter|qu[aá]ter|quinquies))?)\b"
)

# Sequential ley numbers are unique; year is required in the IMPO path.
# Landmarks from live probes + historical numbering.
LANDMARKS = [
    (1, 1830), (200, 1835), (800, 1852), (1500, 1870), (3000, 1895),
    (5000, 1915), (8000, 1930), (10000, 1940), (12000, 1954),
    (14000, 1972), (14701, 1977), (15700, 1985), (16045, 1989),
    (17000, 1998), (17500, 2003), (18000, 2006), (18341, 2008),
    (19000, 2013), (19500, 2017), (19800, 2020), (20000, 2022),
    (20200, 2023), (20300, 2024), (20400, 2025),
]


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


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


def decode_impo(content: bytes, encoding: Optional[str] = None) -> Optional[dict]:
    if not content or not content.lstrip().startswith(b"{"):
        return None
    for enc in (encoding, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            data = json.loads(content.decode(enc, "replace"))
        except Exception:
            continue
        if isinstance(data, dict) and (data.get("nroNorma") or data.get("tipoNorma")):
            return data
    return None


def fetch_impo_json(url: str) -> tuple[Optional[dict], str, str]:
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                     headers={"Accept": "application/json, text/html, */*"})
    except Exception as exc:
        r = None
        log.info("live fail %s %s", url, exc)
    if r is not None:
        if r.status_code == 429:
            wb = af.get_wayback_content(url)
            if wb.get("status") == "success":
                raw = wb.get("content") or b""
                if not raw and wb.get("text"):
                    raw = wb["text"].encode("latin-1", "replace")
                data = decode_impo(raw if isinstance(raw, bytes) else str(raw).encode("utf-8", "replace"))
                if data:
                    return data, wb.get("wayback_url") or url, "wayback"
            return None, url, "fail"
        if r.status_code in (404, 410):
            return None, url, "404"
        if r.status_code == 200 and r.content:
            data = decode_impo(r.content, r.encoding)
            if data:
                return data, r.url or url, "live"
            head = r.content[:200].decode("latin-1", "replace").lower()
            if "<html" in head:
                return None, url, "missing"
    return None, url, "fail"


def guess_year(n: int) -> int:
    lo, hi = LANDMARKS[0], LANDMARKS[-1]
    for a, b in zip(LANDMARKS, LANDMARKS[1:]):
        if a[0] <= n <= b[0]:
            lo, hi = a, b
            break
        if n > b[0]:
            lo, hi = b, LANDMARKS[-1]
    span_n = max(1, hi[0] - lo[0])
    frac = (n - lo[0]) / span_n
    return int(round(lo[1] + frac * (hi[1] - lo[1])))


def candidate_years(n: int) -> list[int]:
    y = guess_year(n)
    out = []
    for d in (0, -1, 1):
        yy = y + d
        if 1830 <= yy <= 2026 and yy not in out:
            out.append(yy)
    return out


def ley_url(nro: str, anio: str) -> str:
    return f"{IMPO}/bases/leyes/{nro}-{anio}?json=true"


def impo_text(data: dict) -> str:
    parts = []
    vistos = (data.get("vistos") or "").strip()
    if vistos:
        parts.append(html_to_text(vistos) if "<" in vistos else vistos)
    arts = data.get("articulos") or []
    if not arts:
        return "\n\n".join(p for p in parts if p).strip()
    # Some IMPO records dump the whole text into article 1.
    if len(arts) == 1:
        body = arts[0].get("textoArticulo") or ""
        parts.append(html_to_text(body) if "<" in body else body)
        return "\n\n".join(p for p in parts if p).strip()
    for art in arts:
        nro = (art.get("nroArticulo") or "").strip()
        tit = (art.get("tituloArticulo") or art.get("titulosArticulo") or "").strip()
        body = art.get("textoArticulo") or ""
        body = html_to_text(body) if "<" in body else body
        head = " ".join(x for x in (f"Artículo {nro}" if nro else "", tit) if x)
        chunk = f"{head}\n{body}".strip() if head else body
        if chunk:
            parts.append(chunk)
    return "\n\n".join(p for p in parts if p).strip()


def cdx_leyes() -> list[dict]:
    items = []
    seen = set()
    try:
        recs = af.search_wayback_machine(
            "impo.com.uy/bases/leyes/",
            match_type="prefix",
            limit=1500,
            collapse="urlkey",
            filter_status="200",
        )
    except Exception as exc:
        log.warning("cdx leyes failed: %s", exc)
        return []
    for rec in recs:
        orig = rec.get("original") or ""
        m = re.search(r"/bases/leyes/(\d+)-(\d{4})", orig)
        if not m:
            continue
        nro, year = m.group(1), m.group(2)
        if nro in seen:
            continue
        seen.add(nro)
        items.append({
            "ident": f"ley-{nro}-{year}",
            "nro": nro,
            "year": year,
            "kind": "ley",
            "priority": 2,
            "title": f"Ley {nro}",
            "url": ley_url(nro, year),
        })
    log.info("cdx leyes unique n=%s", len(items))
    return items


def probe_latest(start: int = 20350, cap: int = 20750) -> int:
    lo, hi = start, start
    last = start
    # exponential find upper bound
    n = start
    while n <= cap:
        found = False
        for y in candidate_years(n):
            data, _, method = fetch_impo_json(ley_url(str(n), str(y)))
            if data and str(data.get("nroNorma") or "") == str(n):
                last = n
                found = True
                break
            if method == "fail":
                break
        if found:
            n += 25
            hi = n
        else:
            hi = n
            break
    # binary-ish walk down from hi
    for n in range(hi, lo - 1, -1):
        for y in candidate_years(n)[:3]:
            data, _, _ = fetch_impo_json(ley_url(str(n), str(y)))
            if data and str(data.get("nroNorma") or "") == str(n):
                log.info("latest ley ~%s/%s", n, y)
                return n
    return last


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 500:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: dict[str, dict] = {}

    def add(it: dict):
        key = it.get("ident") or f"{it.get('kind')}-{it.get('nro')}-{it.get('year')}"
        if not key:
            return
        prev = items.get(key)
        if prev and prev.get("priority", 9) <= it.get("priority", 9):
            return
        items[key] = it

    add({
        "ident": "cn-1967",
        "title": "Constitución de la República Oriental del Uruguay",
        "url": CONST_URL,
        "kind": "constitution",
        "nro": "1967",
        "year": "1967",
        "priority": 0,
    })
    for it in cdx_leyes():
        add(it)
    latest = 20450
    try:
        latest = probe_latest()
    except Exception as exc:
        log.warning("latest probe failed: %s", exc)
    # Prefer a complete modern leyes catalog (return-to-democracy numbering)
    # plus whatever historical official URLs CDX already found. Pre-15700
    # sequential probing is mostly decreto-ley / unused numbers.
    SEQ_START = 15700
    have = {it.get("nro") for it in items.values() if it.get("kind") == "ley"}
    log.info("number range %s..%s (cdx already %s)", SEQ_START, latest, len(have))
    for n in range(SEQ_START, latest + 1):
        nro = str(n)
        if nro in have:
            continue
        y = guess_year(n)
        add({
            "ident": f"ley-{nro}-{y}",
            "title": f"Ley {nro}",
            "url": ley_url(nro, str(y)),
            "kind": "ley",
            "nro": nro,
            "year": str(y),
            "priority": 3,
            "year_guess": True,
        })
    out = list(items.values())
    out.sort(key=lambda x: (x.get("priority", 9), int(re.sub(r"\D", "", x.get("nro") or "0") or 0)))
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in out))
    log.info("discovered n=%s", len(out))
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or it.get("url")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    kind = it.get("kind") or "ley"
    data = None
    used = it.get("url") or ""
    method = "fail"
    if kind == "constitution":
        data, used, method = fetch_impo_json(CONST_URL)
    else:
        nro = str(it.get("nro") or "")
        years = []
        y0 = it.get("year")
        if y0:
            years.append(int(y0) if str(y0).isdigit() else 0)
        if it.get("year_guess") or not data:
            for y in candidate_years(int(nro or 0) or 0):
                if y not in years:
                    years.append(y)
        for y in years:
            if not y:
                continue
            data, used, method = fetch_impo_json(ley_url(nro, str(y)))
            if data and str(data.get("nroNorma") or "") == nro:
                it["year"] = str(data.get("anioNorma") or y)
                break
            data = None
    if not data:
        # Unused numbers / decreto-ley slots are not leyes.
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "skipped_missing", "reason": "not_ley_json"})
        return "skip"
    text = impo_text(data)
    if not text or len(text) < MIN_TEXT:
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    if af.is_challenge(text, 200):
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "failed", "reason": "challenge"})
        return "fail"
    title = (data.get("nombreNorma") or it.get("title") or ident).strip()
    nro = str(data.get("nroNorma") or it.get("nro") or "")
    year = str(data.get("anioNorma") or it.get("year") or "")
    date = iso_date(data.get("fechaPromulgacion") or data.get("fechaPublicacion"))
    tipo = (data.get("tipoNorma") or "Ley").strip()
    is_cn = kind == "constitution" or "constitucion" in tipo.lower() or ident.startswith("cn-")
    if is_cn:
        title = "Constitución de la República Oriental del Uruguay"
        doc_type = "constitution"
        official = "Constitución 1967"
        ident = "cn-1967"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
    else:
        doc_type = "statute"
        official = f"{tipo} {nro}".strip()
        title = f"{official} — {title}" if title and official.lower() not in title.lower() else (title or official)
    docs = split_es(text, rid, used, date, "impo_json")
    # Prefer IMPO article split when structured
    arts = data.get("articulos") or []
    if len(arts) >= 2:
        custom = []
        seen = set()
        for art in arts:
            nra = (art.get("nroArticulo") or "").strip()
            body = art.get("textoArticulo") or ""
            body = html_to_text(body) if "<" in body else body
            if len(body) < 8:
                continue
            label = f"Artículo {nra}" if nra else "Artículo"
            aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
            doc_id = f"{rid}-{aid}"[:180]
            if doc_id in seen:
                continue
            seen.add(doc_id)
            custom.append({
                "id": doc_id, "title": (body.split("\n", 1)[0])[:200],
                "text": f"{label}\n{body}".strip(), "date_filed": date,
                "document_number": label, "source_url": used, "record_type": "article",
                "article_number": label, "law_identifier": rid,
                "metadata": {"text_extraction": {"source": "official", "backend": "impo_json"}},
            })
            if len(custom) >= 4000:
                break
        if len(custom) >= 2:
            docs = custom
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_uy.py",
        eli=used.split("?")[0],
        date=date, official_identifier=official,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": {"method": method},
            "discovery": {"method": "impo_json", "nro": nro, "year": year},
            "official_metadata": {
                "tipoNorma": tipo,
                "nroNorma": nro,
                "anioNorma": year,
                "fechaPromulgacion": data.get("fechaPromulgacion"),
                "fechaPublicacion": data.get("fechaPublicacion"),
                "leyenda": (data.get("leyenda") or "").strip() or None,
                "fetch_method": method,
            },
        },
        extra_fields={
            "canonical_title": title,
            "publication_date": iso_date(data.get("fechaPublicacion")),
            "information_url": used.split("?")[0],
            "canonical_document_url": used,
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
        "https://www.impo.com.uy/",
        "https://www.impo.com.uy/datos-abiertos/",
        CONST_URL.split("?")[0],
        SCHEMA_URL,
        "https://www.impo.com.uy/bases/leyes/",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str):
        notes = (
            f"Constitución 1967 plus leyes from IMPO datos abiertos JSON "
            f"(/bases/leyes/{{nro}}-{{anio}}?json=true). Catalog {len(items)} rows "
            f"(CDX of official IMPO URLs plus sequential leyes ~15700–present with year "
            f"interpolation; missing numbers are unused or decreto-ley). Decretos "
            f"out of scope. Diario Oficial prevails. Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="IMPO Centro de Información Oficial (Diario Oficial / Normativa)",
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
            if n % 40 == 0 or n == len(rest):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(rest), ok, skip, fail)
                write_progress("catalog-backed incomplete")
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
