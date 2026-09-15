#!/usr/bin/env python3
"""Sudan: Official Gazette PDFs from Ministry of Justice files index.

Official: https://www.moj.gov.sd/files/index/28 → files/download/{id}
Many issues are HP Scan image-only PDFs — OCR with tesseract ara+eng.
Live first (verify=False for MoJ TLS). Wayback of official URLs on fail.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, live_get, pdf_to_text, save_instrument, setup_log, slug_id
import archive_fallbacks as af

CC, COUNTRY, LANG = "sd", "Sudan", "ar"
SOURCE_TYPE = "moj_sd_gazette"
LICENSE = (
    "Official Gazette of the Republic of Sudan as published by the Ministry of Justice "
    "(moj.gov.sd). Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.moj.gov.sd/)"
INDEX = "https://www.moj.gov.sd/files/index/28"
DL_RE = re.compile(r"https?://www\.moj\.gov\.sd/files/download/(\d+)", re.I)
log = logging.getLogger("sd")


def ocr_pdf(raw: bytes, *, max_pages: int = 12, dpi: int = 200) -> str:
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


def fetch_pdf(url: str) -> dict:
    out = {"status": "error", "text": "", "content": b"", "method": "", "error": ""}
    body = b""
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(20, 180))
        body = r.content or b""
        if r.status_code == 200 and body[:4] == b"%PDF":
            text = pdf_to_text(body)
            method = "http_pdf"
            if len(text) < 80:
                text = ocr_pdf(body, max_pages=env_int("SD_OCR_PAGES", 12))
                method = "http_pdf_ocr"
            if len(text) >= 80:
                out.update(status="success", text=text, content=body, method=method)
                return out
            out["error"] = "pdf_no_text"
        else:
            out["error"] = f"http_{getattr(r,'status_code','?')}"
    except Exception as exc:
        out["error"] = f"live:{exc}"
    # Wayback optional — HTTPS EOF common from this host
    import os
    if os.environ.get("SD_WAYBACK", "0") != "1":
        return out
    try:
        w = af.get_wayback_content(url)
        if w.get("status") == "success":
            raw_b = w.get("content") or b""
            if isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF":
                text = pdf_to_text(raw_b)
                method = "wayback_pdf"
                if len(text) < 80:
                    text = ocr_pdf(raw_b, max_pages=env_int("SD_OCR_PAGES", 12))
                    method = "wayback_pdf_ocr"
                if len(text) >= 80:
                    out.update(status="success", text=text, content=raw_b, method=method)
                    return out
            out["error"] = (out.get("error") or "") + ";wayback_no_text"
        else:
            out["error"] = (out.get("error") or "") + f";wayback:{w.get('error')}"
    except Exception as exc:
        out["error"] = (out.get("error") or "") + f";wayback:{exc}"
    return out


def discover() -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    try:
        r = live_get(INDEX, ua=UA, verify=False)
        html = r.text or ""
    except Exception as exc:
        log.warning("index fail: %s", exc)
        return items
    # pair nearby title cells loosely: take all downloads on this gazette index page
    for m in DL_RE.finditer(html):
        did = m.group(1)
        ident = f"gazette-{did}"
        if ident in seen:
            continue
        seen.add(ident)
        # look back for title snippet
        start = max(0, m.start() - 400)
        chunk = html[start:m.start()]
        tm = re.search(r"(الجريدة[^<]{0,100}|جريدة رسمية[^<]{0,100})", chunk)
        title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else f"الجريدة الرسمية {did}"
        url = f"https://www.moj.gov.sd/files/download/{did}"
        items.append((ident, url, title))
    log.info("discovered %s downloads from index/28", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 7200)
    t_start = time.time()
    done = existing_ids(CC)
    items = discover()
    ok = skip = fail = 0
    for ident, url, title in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
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
        # stash raw PDF
        raw_dir = Path(__import__("common").ROOT) / CC / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        if got.get("content"):
            (raw_dir / f"{ident}.pdf").write_bytes(got["content"])
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_sd.py",
            extra_meta={"fetch_method": got.get("method"), "ocr_lang": "ara+eng"},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident, len(text), got.get("method"))
        else:
            fail += 1
        time.sleep(0.5)
    write_summary(
        CC, country=COUNTRY, source="Sudan MoJ Official Gazette (files/index/28)",
        source_urls=[INDEX, "https://www.moj.gov.sd/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="gazette PDF issues; image-only via tesseract ara+eng",
        notes="Official moj.gov.sd only. Scanned PDFs OCR'd ara+eng. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s discovered=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
