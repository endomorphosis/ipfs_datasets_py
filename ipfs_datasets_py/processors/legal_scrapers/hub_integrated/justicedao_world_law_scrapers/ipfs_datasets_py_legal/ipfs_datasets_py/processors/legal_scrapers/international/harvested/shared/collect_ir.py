#!/usr/bin/env python3
"""Iran: National System of Laws / DOTIC (dotic.ir) official PDFs + Wayback."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text, is_garbage_text, normalize_rtl_text

CC, COUNTRY, LANG = "ir", "Iran", "fa"
SOURCE_TYPE = "dotic_iran"
LICENSE = (
    "Official laws of the Islamic Republic of Iran as published via DOTIC (dotic.ir). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.dotic.ir/)"
# ماده واحده + ماده N; no trailing \\b; RTL digits normalized in split_custom
ART = re.compile(r"(?m)^\s*((?:ماده)\s*(?:واحده|\d+)|(?:Article|Art\.?)\s*\d+)(?!\d)")
log = logging.getLogger("ir")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "dotic.ir" not in low:
            return  # includes media.dotic.ir / update.dotic.ir
        if ".pdf" not in low:
            return
        if any(x in low for x in ("logo", "banner", "css", "font")):
            return
        if url in seen:
            return
        ident = Path(url.split("?")[0]).stem[:160]
        seen.add(url)
        items.append((ident, url))
    for prefix in (
        "www.dotic.ir/Attachs/",
        "dotic.ir/Attachs/",
        "media.dotic.ir/uploads/",
        "media.dotic.ir/",
        "www.dotic.ir/download/",
        "dotic.ir/download/",
        "www.dotic.ir/",
        "dotic.ir/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 800), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    log.info("catalog %s", len(items))
    return items


def recover_text(got: dict) -> tuple[str, str]:
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
        # Persian tessdata unavailable; ara is closest script support
        new_text, how, _pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="ara",
            ocr_max_pages=env_int("OCR_PAGES", 30),
        )
        new_text = normalize_rtl_text(new_text)
        if new_text and not is_garbage_text(new_text) and len(new_text) >= 80:
            return new_text, f"{method}+{how}" if method else how
    return text, method


def pick_title(text: str, ident: str) -> str:
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
        title = pick_title(text, ident)
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ir.py",
            article_re=ART, extra_meta={"fetch_method": method},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], method, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="DOTIC Iran",
        source_urls=["https://www.dotic.ir/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official dotic.ir PDFs)",
        notes="Official DOTIC law PDFs. RTL normalize + ara OCR fallback for corrupt text layers. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
