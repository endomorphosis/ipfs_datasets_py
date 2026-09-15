#!/usr/bin/env python3
"""Palestine: decrees/laws PDFs from mjr.ogb.gov.ps (Electronic Official Gazette reference).

Official only: https://mjr.ogb.gov.ps/Decrees/Index + Details + Download
Not Muqtafi / Birzeit. Live-first; Wayback of official mjr URLs on fail.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, live_get, pdf_to_text, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ps", "Palestine", "ar"
SOURCE_TYPE = "ogb_mjr"
LICENSE = (
    "Official texts of the State of Palestine as published via the Electronic Official "
    "Gazette Reference (mjr.ogb.gov.ps / Official Gazette Bureau). Authentic gazette "
    "text prevails. Not legal advice. Not Muqtafi."
)
UA = "legal-corpora-collector/1.0 (research; source=https://mjr.ogb.gov.ps/)"
BASE = "https://mjr.ogb.gov.ps"
DETAIL_RE = re.compile(r'href=["\'](/Decrees/Details/(\d+)/[^"\']+)["\']', re.I)
DL_RE = re.compile(r'href=["\'](/Decrees/Download/\?p=[^"\']+\.pdf[^"\']*)["\']', re.I)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
H1_RE = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.I | re.S)
log = logging.getLogger("ps")


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def discover() -> list[tuple[str, str, str]]:
    """Return (ident, detail_url, title_guess). Paginate pageNumber (15/page)."""
    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    y0 = env_int("PS_YEAR_FROM", 1994)
    y1 = env_int("PS_YEAR_TO", 2026)
    max_pages = env_int("PS_MAX_PAGES", 80)
    for year in range(y1, y0 - 1, -1):
        year_n = 0
        for page in range(1, max_pages + 1):
            url = (
                f"{BASE}/Decrees/Index?FromYear={year}&ToYear={year}"
                f"&pageNumber={page}"
            )
            try:
                r = live_get(url, ua=UA, verify=True)
                html = r.text or ""
            except Exception as exc:
                log.warning("index %s p%s fail: %s", year, page, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            page_n = 0
            for m in DETAIL_RE.finditer(html):
                path, did = m.group(1), m.group(2)
                if did in seen:
                    continue
                seen.add(did)
                full = urljoin(BASE, path)
                title = unquote(path.split("/")[-1].replace("-", " "))[:200]
                items.append((f"decree-{did}", full, title))
                page_n += 1
                year_n += 1
            log.info("year %s page=%s details=%s total=%s", year, page, page_n, len(items))
            time.sleep(0.35)
            if page_n == 0:
                break
        if year_n:
            log.info("year %s total_details=%s", year, year_n)
    return items


def pdf_url_from_detail(detail_url: str) -> tuple[str, str]:
    try:
        r = live_get(detail_url, ua=UA, verify=True)
        html = r.text or ""
    except Exception as exc:
        return "", f"detail:{exc}"
    if getattr(r, "status_code", 0) != 200:
        return "", f"detail_http_{r.status_code}"
    m = DL_RE.search(html)
    if not m:
        return "", "no_download"
    pdf = urljoin(BASE, m.group(1).replace("&amp;", "&"))
    title = ""
    tm = H1_RE.search(html) or TITLE_RE.search(html)
    if tm:
        title = strip_tags(tm.group(1))[:240]
    return pdf, title


def ocr_pdf(raw: bytes, *, max_pages: int = 8, dpi: int = 180) -> str:
    """OCR image-only Official Gazette PDFs (tesseract ara+eng)."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "x.pdf"
            pdf.write_bytes(raw)
            prefix = Path(td) / "p"
            subprocess.run(
                ["pdftoppm", "-f", "1", "-l", str(max_pages), "-png", "-r", str(dpi), str(pdf), str(prefix)],
                check=False, capture_output=True, timeout=300,
            )
            parts = []
            for img in sorted(Path(td).glob("p-*.png")):
                proc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "ara+eng", "--psm", "6"],
                    check=False, capture_output=True, timeout=180,
                )
                if proc.returncode == 0 and proc.stdout:
                    parts.append(proc.stdout.decode("utf-8", "replace"))
            return "\n".join(parts).strip()
    except Exception as exc:
        log.warning("ocr fail: %s", exc)
        return ""


def fetch_ps_pdf(pdf_url: str) -> dict:
    """Live PDF first; OCR scans when pdftotext is empty; Wayback last."""
    got = fetch_official(pdf_url, ua=UA, verify=True, min_text=80)
    if got.get("status") == "success":
        return got
    # OCR path for CamScanner / image-only gazette pages
    try:
        r = live_get(pdf_url, ua=UA, verify=True, timeout=(20, 180))
        body = r.content or b""
        if getattr(r, "status_code", 0) == 200 and body[:4] == b"%PDF":
            text = pdf_to_text(body)
            method = "http_pdf"
            if len(text) < 80:
                text = ocr_pdf(body, max_pages=env_int("PS_OCR_PAGES", 8))
                method = "http_pdf_ocr"
            if len(text) >= 80:
                return {"status": "success", "text": text, "content": body, "method": method, "error": ""}
    except Exception as exc:
        got = dict(got or {})
        got["error"] = (got.get("error") or "") + f";ocr_live:{exc}"
    return got if got else {"status": "error", "text": "", "error": "fetch_failed", "method": ""}


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 1500)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    items = discover()
    ok = skip = fail = 0
    for ident, detail, title_guess in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        pdf_url, title2 = pdf_url_from_detail(detail)
        title = title2 or title_guess or ident
        if not pdf_url:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": detail, "reason": title2 or "no_pdf"})
            continue
        # only official host
        if "mjr.ogb.gov.ps" not in pdf_url:
            fail += 1
            continue
        got = fetch_ps_pdf(pdf_url)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": pdf_url, "reason": got.get("error")})
            continue
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=pdf_url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_ps.py",
            extra_meta={"fetch_method": got.get("method"), "detail_url": detail},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident, len(text), got.get("method"))
        else:
            fail += 1
        time.sleep(0.5)
    write_summary(
        CC, country=COUNTRY, source="Palestine mjr.ogb.gov.ps Decrees PDFs",
        source_urls=[f"{BASE}/", f"{BASE}/Decrees/Index"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="decrees/laws PDF snapshot via official Decrees Index",
        notes="Official mjr.ogb.gov.ps only. Not Muqtafi. Live-first; Wayback of official URLs on fail.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s discovered=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
