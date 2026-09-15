#!/usr/bin/env python3
"""Suriname: DNA Staatsblad wet PDFs (dna.sr/media) + key verkiezingen.gov.sr texts."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "sr", "Suriname", "nl"
SOURCE_TYPE = "dna_staatsblad"
LICENSE = (
    "De Nationale Assemblée / Staatsblad van de Republiek Suriname (dna.sr). "
    "Authentic Staatsblad text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.dna.sr/)"
)
ART = re.compile(r"(?im)^\s*((?:Artikel|Art\.?)\s+[0-9]+[a-zA-Z]?)\b")
log = logging.getLogger("sr")
MAX_PDF = env_int("MAX_PDF_BYTES", 6 * 1024 * 1024)
LAW_RE = re.compile(r"(wet|s[\.-]?b|staatsblad|grondwet|besluit)", re.I)
SKIP_RE = re.compile(r"(begroting|budget|naturalisatie|naturalisatie_|holder__|compleet\.pdf)", re.I)
SEED = [
    "https://verkiezingen.gov.sr/storage/pdf/GRONDWET.pdf",
    "https://verkiezingen.gov.sr/storage/pdf/Kiesregeling.pdf",
    "https://verkiezingen.gov.sr/storage/pdf/Kiesbesluit.pdf",
]


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if ".pdf" not in low:
            return
        if not LAW_RE.search(low):
            return
        if SKIP_RE.search(low):
            return
        host_ok = ("dna.sr" in low) or ("verkiezingen.gov.sr" in low)
        if not host_ok:
            return
        if url in seen:
            return
        ident = Path(url.split("?")[0]).stem[:160]
        seen.add(url)
        items.append((ident, url))
    for u in SEED:
        add(u)
    for prefix in ("www.dna.sr/media/", "dna.sr/media/"):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 2000),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    # Prefer wet/grondwet over miscellaneous besluit
    items.sort(key=lambda it: (0 if "grondwet" in it[1].lower() else 1 if "wet" in it[1].lower() else 2, it[1]))
    log.info("catalog %s", len(items))
    return items


def fetch_pdf(url: str) -> dict:
    try:
        r = requests.get(url, timeout=(20, 120), verify=False, headers={"User-Agent": UA})
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    if r.status_code != 200:
        return {"status": "error", "error": f"http_{r.status_code}"}
    raw = r.content or b""
    if raw[:4] != b"%PDF":
        return {"status": "error", "error": "not_pdf"}
    if len(raw) > MAX_PDF:
        return {"status": "error", "error": f"pdf_too_large:{len(raw)}"}
    ocr_lang = os.environ.get("OCR_LANG", "nld+eng" if Path("/home/box/tessdata/nld.traineddata").exists() else "eng")
    ocr_pages = env_int("OCR_PAGES", 8)
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    text, how, pages = extract_pdf_text(
        raw, enable_ocr=True, ocr_lang=ocr_lang.split("+")[0] if "+" in ocr_lang else ocr_lang,
        ocr_max_pages=ocr_pages,
    )
    # pdf_extract_lib may not accept nld+eng; if nld available try nld then eng
    if (not text or len(text) < 120) and Path("/home/box/tessdata/nld.traineddata").exists():
        text, how, pages = extract_pdf_text(raw, enable_ocr=True, ocr_lang="nld", ocr_max_pages=ocr_pages)
    if not text or len(text) < 100:
        return {"status": "error", "error": f"extract_failed:{how}", "method": how}
    return {"status": "success", "text": text, "method": how, "content": raw}


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if str(got.get("method") or "").startswith("ocr"):
            ocr_used += 1
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_sr.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="DNA / Staatsblad Suriname",
        source_urls=["https://www.dna.sr/", "https://verkiezingen.gov.sr/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (dna.sr/media Staatsblad wet PDFs; OCR on scans)",
        notes=f"Official DNA media SB wet PDFs + verkiezingen Grondwet/Kiesregeling. OCR used={ocr_used}. Not vLex. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
