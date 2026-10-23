#!/usr/bin/env python3
"""Bolivia: Gaceta Oficial de Bolivia (HTTP; HTTPS TLS often fails) + Wayback."""
from __future__ import annotations
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls, env_int, fetch_official_prefer_pdf, pdf_to_text, save_instrument,
    setup_log, slug_id,
)
import archive_fallbacks as af

CC, COUNTRY, LANG = "bo", "Bolivia", "es"
SOURCE_TYPE = "gaceta_oficial_bo"
LICENSE = (
    "Official Gazette of the Plurinational State of Bolivia "
    "(gacetaoficialdebolivia.gob.bo). Authentic Gaceta text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.gacetaoficialdebolivia.gob.bo/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("bo")
HOME = "http://www.gacetaoficialdebolivia.gob.bo/"

PREFIXES = [
    "gacetaoficialdebolivia.gob.bo/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/",
    "www.gacetaoficialdebolivia.gob.bo/app/webroot/archivos/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/MOF/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/presidentes/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/leyes/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/decretos/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/resoluciones/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/archivos/constitucionales/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/files/",
    "gacetaoficialdebolivia.gob.bo/files/",
    "gacetaoficialdebolivia.gob.bo/ediciones/",
    "gacetaoficialdebolivia.gob.bo/gacetas/",
    "gacetaoficialdebolivia.gob.bo/normas/",
    "gacetaoficialdebolivia.gob.bo/norma/",
    "gacetaoficialdebolivia.gob.bo/busqueda/",
    "gacetaoficialdebolivia.gob.bo/descargas/",
    "www.gacetaoficialdebolivia.gob.bo/",
    "www.gacetaoficialdebolivia.gob.bo/normas/",
    "www.gacetaoficialdebolivia.gob.bo/gacetas/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/uploads/",
    "gacetaoficialdebolivia.gob.bo/app/webroot/pdf/",
]



def _ocr_pdf(pdf: bytes) -> str:
    """Optional OCR for scanned Gaceta PDFs (ALLOW_OCR=1)."""
    if not pdf or pdf[:4] != b"%PDF":
        return ""
    if os.environ.get("ALLOW_OCR", "0") not in ("1", "true", "True", "yes"):
        return ""
    try:
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.pdf"
            src.write_bytes(pdf)
            # pdftoppm first page(s) then tesseract spa
            max_pages = int(os.environ.get("MAX_OCR_PAGES", "8") or 8)
            out_prefix = Path(d) / "p"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", str(max_pages), str(src), str(out_prefix)],
                check=False, capture_output=True, timeout=180,
            )
            parts = []
            for img in sorted(Path(d).glob("p-*.png"))[:max_pages]:
                proc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "spa+eng", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if proc.returncode == 0 and proc.stdout:
                    parts.append(proc.stdout.decode("utf-8", "replace"))
            return "\n".join(parts).strip()
    except Exception as exc:
        log.info("ocr fail: %s", exc)
        return ""


def discover():
    items, seen = [], set()

    def add(url, ts=None):
        url = (url or "").split("#")[0].strip()
        if not url:
            return
        if not url.startswith("http"):
            url = urljoin(HOME, url)
        url = url.replace("://www.gacetaoficialdebolivia.gob.bo:80/", "://www.gacetaoficialdebolivia.gob.bo/")
        url = url.replace("://gacetaoficialdebolivia.gob.bo:80/", "://gacetaoficialdebolivia.gob.bo/")
        key = url.lower().rstrip("/")
        if key in seen:
            return
        # keep .pdf, archivos, or normas PDF endpoints (mime may be pdf without .pdf suffix)
        low = url.lower()
        if not (
            low.endswith(".pdf")
            or "/archivos/" in low
            or "vergratis" in low
            or "descargarpdf" in low
            or ".pdf" in low
        ):
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(key)
        items.append((ident, url, ts))

    add("http://www.gacetaoficialdebolivia.gob.bo/app/webroot/archivos/CONSTITUCION.pdf")
    try:
        r = http_get(HOME, ua=UA, sleep=0.3)
        if r.status_code == 200:
            for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text or "", re.I):
                add(href)
    except Exception as exc:
        log.info("home %s", exc)

    limit = env_int("CDX_LIMIT", 2500)
    for pref in PREFIXES:
        # With mime filter
        for h in cdx_urls(pref, limit=limit, match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            add(orig, h.get("timestamp"))
        # Broader: no mime filter, accept .pdf paths (Wayback sometimes mislabels)
        try:
            hits = af.search_wayback_machine(
                pref, limit=min(limit, 1500), match_type="prefix",
                collapse=None, extra_filters=None,
            ) or []
        except Exception as exc:
            log.info("cdx broad %s err %s", pref, exc)
            hits = []
        for h in hits:
            orig = h.get("original") or ""
            if orig.lower().endswith(".pdf") or "/archivos/" in orig.lower():
                add(orig, h.get("timestamp"))
        log.info("after prefix %s catalog=%s", pref, len(items))
        if len(items) >= env_int("CATALOG_CAP", 600):
            break

    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 50)
    max_seconds = env_int("MAX_SECONDS", 3600)
    target = env_int("TARGET_LAWS", 93)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    from common import ROOT
    corpus = lambda: sum(1 for _ in (ROOT / CC / "instruments").glob("*.json"))

    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if corpus() >= target and ok >= 1:
            log.info("target %s reached", target)
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official_prefer_pdf(url, ua=UA, verify=False, min_text=80, wayback_ts=ts)
        text = got.get("text") or ""
        method = got.get("method") or ""
        if len(text) < 80 and got.get("content"):
            # OCR fallback for scanned PDFs
            ocr = _ocr_pdf(got["content"] if isinstance(got["content"], (bytes, bytearray)) else b"")
            if len(ocr) >= 80:
                text = ocr
                method = (method or "pdf") + "+ocr"
        if len(text) < 80:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bo.py",
            article_re=ART, extra_meta={"fetch_method": method, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s corpus=%s", ident[:70], method, corpus())
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Gaceta Oficial de Bolivia",
        source_urls=["http://www.gacetaoficialdebolivia.gob.bo/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (HTTP PDFs + timestamped Wayback)",
        notes="HTTPS TLS often fails; HTTP and CDX-timestamped Wayback of official URLs. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s corpus=%s", ok, skip, fail, corpus())


if __name__ == "__main__":
    main()
