#!/usr/bin/env python3
"""Mexico: Leyes Federales vigentes (Cámara de Diputados LeyesBiblio consolidations).

Official sources only:
  - https://www.diputados.gob.mx/LeyesBiblio/index.htm
  - Diario Oficial de la Federación / SIDOF (authentic gazette)
    https://sidofqa.segob.gob.mx/dof/sidof/diarios/{year}

Does not use commercial Mexican law databases. Prefers LeyesBiblio
PDF consolidations (in-force federal laws ~314). DOF dates recorded
as provenance; authentic source is the DOF.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "mx"
COUNTRY = "Mexico"
SOURCE_TYPE = "leyes_biblio"
LICENSE = (
    "Mexican official legislative texts (Leyes Federales vigentes) published by "
    "the Cámara de Diputados and the Diario Oficial de la Federación. Public "
    "sector information / official texts; Cámara de Diputados LeyesBiblio "
    "consolidations. Authentic source is the DOF. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.diputados.gob.mx/LeyesBiblio/"
BASE = "https://www.diputados.gob.mx/LeyesBiblio/"
INDEX = BASE + "index.htm"
SIDOF = "https://sidofqa.segob.gob.mx/dof/sidof/diarios/"
WORKERS = 4
SLEEP = 0.45
log = logging.getLogger("mx")

ART_MX = re.compile(
    r"(?im)^\s*((?:Art(?:ículo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[a-zA-Z])?(?:\s*bis|\s*ter|\s*qu[aá]ter)?)\b"
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


def split_mx_articles(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_MX.finditer(text or ""))
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
            "id": doc_id,
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "leyes_biblio_pdf"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def parse_index(html: str) -> list[dict]:
    items: list[dict] = []
    seen = set()
    # Split on table rows; each law is one <tr> with pdf + title.
    parts = re.split(r"(?i)<tr\b", html)
    for part in parts:
        pdfs = re.findall(r'href=["\'](pdf/[^"\']+\.pdf)["\']', part, re.I)
        pdf_mov = re.findall(r'href=["\'](pdf_mov/[^"\']+\.pdf)["\']', part, re.I)
        docs = re.findall(r'href=["\'](doc/[^"\']+\.doc)["\']', part, re.I)
        refs = re.findall(r'href=["\'](ref/[^"\']+\.htm)["\']', part, re.I)
        if not pdfs and not pdf_mov:
            continue
        title = ""
        for ref in refs:
            m = re.search(
                re.escape(ref) + r'["\'][^>]*>\s*(?:<[^>]+>)*([^<]{8,200})',
                part, re.I,
            )
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
                if title:
                    break
        if not title:
            src = (pdf_mov or pdfs or docs or [""])[0]
            stem = Path(src).stem.replace("_", " ")
            title = stem
        dofs = re.findall(r"DOF\s+(\d{2}/\d{2}/\d{4})", part, re.I)
        # First DOF is typically original publication; last is last reform listed in the row.
        dof_orig = dofs[0] if dofs else None
        dof_last = dofs[-1] if dofs else None
        ident = Path((pdfs or pdf_mov)[0]).stem
        if ident.lower() in seen:
            continue
        seen.add(ident.lower())
        items.append({
            "id": ident,
            "title": title,
            "pdf": pdfs[0] if pdfs else None,
            "pdf_mov": pdf_mov[0] if pdf_mov else None,
            "doc": docs[0] if docs else None,
            "ref": refs[0] if refs else None,
            "dof_orig": dof_orig,
            "dof_last": dof_last,
        })
    return items


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    if cat.exists() and cat.stat().st_size > 1000:
        items = []
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s", len(items))
            return items
    r = http_get(INDEX, ua=UA, sleep=0.3, timeout=(20, 90), retries=5,
                 headers={"Accept": "text/html, */*"})
    if r.status_code != 200 or not r.content:
        log.error("index status=%s", r.status_code)
        return []
    html = r.content.decode("latin-1", "replace")
    (ROOT / CC / "raw" / "index.htm").write_bytes(r.content)
    items = parse_index(html)
    for it in items:
        append_catalog(CC, it)
    log.info("discovered %s leyes federales", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    ident = (it.get("id") or "").strip()
    if not ident:
        return "fail"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text = ""
    src = None
    fmt = None
    raw = b""
    for key, label in (("pdf", "pdf"), ("pdf_mov", "pdf_mov"), ("doc", "doc")):
        rel = it.get(key)
        if not rel:
            continue
        url = urljoin(BASE, rel)
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=4,
                     headers={"Accept": "application/pdf, application/msword, */*"})
        if r.status_code != 200 or not r.content or len(r.content) < 80:
            continue
        raw = r.content
        if raw[:4] == b"%PDF":
            text = pdf_to_text(raw)
            fmt = "pdf"
            src = url
        elif key == "doc" and len(raw) > 80:
            # Word .doc: try antiword / catdoc / python fallback via strings
            try:
                with tempfile.NamedTemporaryFile(suffix=".doc", delete=True) as tmp:
                    tmp.write(raw)
                    tmp.flush()
                    for cmd in (["antiword", tmp.name], ["catdoc", tmp.name]):
                        try:
                            proc = subprocess.run(cmd, check=False, capture_output=True, timeout=60)
                            if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 80:
                                text = proc.stdout.decode("utf-8", "replace").strip()
                                break
                        except FileNotFoundError:
                            continue
            except Exception:
                pass
            fmt = "doc"
            src = url
        if text and len(text) >= 40:
            break
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": urljoin(BASE, it.get("pdf") or ""),
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    date = iso_date(it.get("dof_last") or it.get("dof_orig"))
    title = it.get("title") or ident
    docs = split_mx_articles(text, rid, src, date)
    doc_type = "constitution" if ident.upper() == "CPEUM" or "constituci" in title.lower() else (
        "code" if title.lower().startswith("c") and "digo" in title.lower().replace("ó", "o") else "statute"
    )
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="mx-leyes-biblio",
        eli=None, date=date, official_identifier=ident,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {"method": "leyesbiblio_index", "catalog_identifier": ident, "seed_url": INDEX},
            "official_metadata": {
                "pdf": it.get("pdf"),
                "pdf_mov": it.get("pdf_mov"),
                "doc": it.get("doc"),
                "ref": it.get("ref"),
                "dof_orig": it.get("dof_orig"),
                "dof_last": it.get("dof_last"),
                "document_format": fmt,
            },
        },
        extra_fields={
            "canonical_title": title,
            "publication_date": iso_date(it.get("dof_orig")),
            "last_modified_date": iso_date(it.get("dof_last")),
            "information_url": urljoin(BASE, it.get("ref") or "index.htm"),
            "canonical_document_url": urljoin(BASE, it.get("pdf") or src),
        },
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    source_urls = [
        INDEX,
        BASE,
        "https://www.diputados.gob.mx/LeyesBiblio/",
        "https://sidofqa.segob.gob.mx/dof/sidof/diarios/2026",
        "https://www.dof.gob.mx/",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))
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
            if n % 25 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Cámara de Diputados LeyesBiblio (Leyes Federales vigentes)",
                    source_urls=source_urls, license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Leyes Federales vigentes consolidations from LeyesBiblio index.htm.",
                    last_run=utcnow(),
                )
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        f"In-force federal law consolidations from Cámara de Diputados LeyesBiblio "
        f"({len(items)} index rows). PDF preferred, then pdf_mov, then .doc. "
        f"Authentic source is the Diario Oficial de la Federación (DOF / SIDOF). "
        f"State/municipal law not included. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Cámara de Diputados LeyesBiblio (Leyes Federales vigentes)",
        source_urls=source_urls, license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
