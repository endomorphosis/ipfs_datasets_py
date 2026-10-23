#!/usr/bin/env python3
"""Iraq: Ministry of Justice uploaded gazette/law PDFs (moj.gov.iq/uploaded)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text, is_garbage_text, normalize_rtl_text

CC, COUNTRY, LANG = "iq", "Iraq", "ar"
SOURCE_TYPE = "moj_iraq"
LICENSE = (
    "Ministry of Justice of the Republic of Iraq (moj.gov.iq). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.moj.gov.iq/)"
# Dashes allowed (OCR); no trailing \\b (breaks before Arabic letters); digits after RTL normalize
ART = re.compile(r"(?m)^\s*((?:المادة|مادة|Article|Art\.?)\s*[-–—:]*\s*\d+)(?!\d)")
log = logging.getLogger("iq")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "moj.gov.iq" not in low:
            return
        if ".pdf" not in low and ".PDF" not in url:
            return
        # skip non-law docs
        if any(x in low for x in ("ensaf", "kanonj", "brochure", "form", "logo")):
            return
        if url in seen:
            return
        stem = Path(unquote(url.split("?")[0])).stem
        ident = re.sub(r"[^\w.\-]+", "-", stem).strip("-")[:160] or "moj-doc"
        seen.add(url)
        items.append((ident, url))
    for prefix in (
        "www.moj.gov.iq/uploaded/",
        "moj.gov.iq/uploaded/",
        "www.moj.gov.iq/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    log.info("catalog %s", len(items))
    return items


def recover_text(got: dict) -> tuple[str, str]:
    """Normalize RTL; OCR when pdftotext/ToUnicode dump is garbage."""
    text = got.get("text") or ""
    method = got.get("method") or ""
    text = normalize_rtl_text(text)
    if text and not is_garbage_text(text) and len(text) >= 100:
        return text, method
    raw = got.get("content") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if raw and (raw[:4] == b"%PDF" or b"%PDF" in raw[:8192]):
        if raw[:4] != b"%PDF":
            raw = raw[raw.find(b"%PDF"):]
        new_text, how, _pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="ara",
            ocr_max_pages=env_int("OCR_PAGES", 30),
        )
        new_text = normalize_rtl_text(new_text)
        if new_text and not is_garbage_text(new_text) and len(new_text) >= 80:
            return new_text, f"{method}+{how}" if method else how
    return text, method


def pick_title(text: str, ident: str, url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    if sum(1 for ch in stem if "\u0600" <= ch <= "\u06FF") >= 4:
        return stem[:240]
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) < 12:
            continue
        ar = sum(1 for ch in s if "\u0600" <= ch <= "\u06FF")
        if ar >= 8 and "(cid:" not in s and s.count("@") < 2:
            return s[:240]
    return ident[:240]


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=100)
        if got.get("status") != "success" and not (got.get("content") or b""):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        text, method = recover_text(got)
        if not text or len(text) < 80 or is_garbage_text(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "garbage_or_short_text"})
            continue
        title = pick_title(text, ident, url)
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_iq.py",
            article_re=ART, extra_meta={"fetch_method": method},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], method, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Iraq Ministry of Justice",
        source_urls=["https://www.moj.gov.iq/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official moj.gov.iq uploaded PDFs)",
        notes="Official MoJ PDFs. Arabic OCR used when ToUnicode/text layer is corrupt. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
