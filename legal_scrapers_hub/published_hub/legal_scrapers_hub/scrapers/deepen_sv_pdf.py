#!/usr/bin/env python3
"""El Salvador deepen: replace 1847 garbage Diario scans with official Asamblea / Diario
PDFs that have real text layers. Uses pdf_extract_lib (IntegratedPDFProcessor-style).

Official only: asamblea.gob.sv, diariooficial.gob.sv. No jurisprudence vault (court cases).
"""
from __future__ import annotations
import json, logging, re, shutil, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_instrument, write_summary, base_record, slug_id
from world_lib import cdx_urls, env_int, setup_log
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, is_garbage_text

CC, COUNTRY, LANG = "sv", "El Salvador", "es"
SOURCE_TYPE = "asamblea_diario_oficial_sv"
LICENSE = (
    "Asamblea Legislativa / Diario Oficial de El Salvador. "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.asamblea.gob.sv/)"
log = logging.getLogger("sv_deepen")


def fetch_pdf_bytes(url: str, ts: str | None = None) -> tuple[bytes, str, str]:
    """Live then Wayback id_ with optional CDX timestamp. Returns (bytes, method, final_url)."""
    import requests
    requests.packages.urllib3.disable_warnings()
    # live
    try:
        r = requests.get(url, timeout=(15, 60), verify=False, headers={"User-Agent": UA})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content, "http_pdf", url
    except Exception as exc:
        log.debug("live fail %s: %s", url, exc)
    # wayback with ts
    if ts:
        w = af.get_wayback_content(url, timestamp=ts)
        body = w.get("content") or b""
        if w.get("status") == "success" and body[:4] == b"%PDF":
            return body, "wayback_pdf", w.get("wayback_url") or url
    # wayback without ts / latest
    w = af.get_wayback_content(url)
    body = w.get("content") or b""
    if w.get("status") == "success" and body[:4] == b"%PDF":
        return body, "wayback_pdf", w.get("wayback_url") or url
    return b"", "fail", url


def discover() -> list[tuple[str, str, str | None]]:
    """Return (ident, url, cdx_ts)."""
    items, seen = [], set()

    def add(url: str, ts: str | None = None):
        url = (url or "").split("#")[0].split("?")[0]
        url = url.replace("http://", "https://").replace(":80/", "/")
        # normalize encoded paths for boveda skip already
        low = url.lower()
        if "jurisprudencia.gob.sv" in low:  # court vault, not statutes
            return
        if "historia" in low or "etica" in low or "ventana-etica" in low:
            return
        if ".pdf" not in low:
            return
        if not any(h in low for h in ("asamblea.gob.sv", "diariooficial.gob.sv")):
            return
        key = low
        if key in seen:
            return
        seen.add(key)
        stem = Path(unquote(urlparse(url).path)).stem[:140] or "sv-doc"
        items.append((stem, url.replace("https://", "http://") if "asamblea" in low else url, ts))

    # Constitution + decretos from Asamblea CDX
    for prefix in (
        "asamblea.gob.sv/asamblea-legislativa/constitucion/",
        "www.asamblea.gob.sv/asamblea-legislativa/constitucion/",
        "www.asamblea.gob.sv/comisiones-legislativas/",
        "asamblea.gob.sv/comisiones-legislativas/",
        "www.diariooficial.gob.sv/diarios/201",
        "diariooficial.gob.sv/diarios/201",
        "www.diariooficial.gob.sv/diarios/202",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 120), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            add(orig, h.get("timestamp"))
    log.info("catalog %s", len(items))
    return items


def quarantine_historical():
    """Move 1847-1859 garbage Diario scans out of instruments."""
    instr = ROOT / CC / "instruments"
    qdir = ROOT / CC / "quarantine_historical"
    qdir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for p in list(instr.glob("*.json")):
        if re.search(r"sv-18(4|5)\d", p.stem):
            shutil.move(str(p), str(qdir / p.name))
            moved += 1
    log.info("quarantined historical %s", moved)
    return moved


def main():
    setup_log(CC, "sv_deepen")
    t0 = utcnow()
    quarantine_historical()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    ocr_used = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        raw, method, final_url = fetch_pdf_bytes(url, ts)
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "pdf_fetch_fail"})
            continue
        text, how, pages = extract_pdf_text(raw, enable_ocr=True, ocr_lang="spa+eng", ocr_max_pages=25)
        if how.startswith("ocr"):
            ocr_used += 1
        if not text or len(text) < 120 or is_garbage_text(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"thin_or_garbage:{how}"})
            continue
        docs, kind = honest_split(CC, text, rid, url)
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        rec = base_record(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="deepen_sv_pdf.py",
            documents=docs,
            extra_meta={
                "fetch_method": method,
                "pdf_parser": "ipfs_datasets_py.IntegratedPDFProcessor",
                "extract_method": how,
                "pages": pages,
                "article_split": {"method": kind, "count": len(docs)},
                "wayback_ts": ts,
                "fetch_url": final_url,
            },
        )
        write_instrument(CC, rec)
        ok += 1
        done.add(rid)
        log.info("ok %s method=%s extract=%s arts=%s chars=%s", ident[:60], method, how, len(docs), len(text))
    write_summary(
        CC, country=COUNTRY, source="Asamblea Legislativa / Diario Oficial SV",
        source_urls=["https://www.asamblea.gob.sv/", "https://www.diariooficial.gob.sv/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official Asamblea/Diario PDFs)",
        notes=f"Replaced 1847 garbage scans. OCR used on {ocr_used} docs. Honest Art. splits. Not legal advice.",
        last_run=t0,
    )
    # counts
    laws = arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        rec = json.loads(p.read_text())
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
    print(json.dumps({"ok": ok, "skip": skip, "fail": fail, "ocr_used": ocr_used, "laws": laws, "arts": arts}))


if __name__ == "__main__":
    main()
