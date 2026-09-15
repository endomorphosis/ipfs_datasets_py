#!/usr/bin/env python3
"""South Sudan: MoJCA laws PDFs (mojca.gov.ss) via CDX/Wayback + live list pages.

Package-only foothold. No Hub-upload. Not legal advice.
"""
from __future__ import annotations
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text, is_garbage_text

CC, COUNTRY, LANG = "ss", "South Sudan", "en"
SOURCE_TYPE = "ss_mojca_laws"
LICENSE = (
    "Ministry of Justice and Constitutional Affairs of South Sudan (mojca.gov.ss). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://mojca.gov.ss/laws/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?|Section|SECTION)\s+[0-9]+[A-Za-z]?)\b")
log = logging.getLogger("ss")
HOSTS = ("mojca.gov.ss", "www.mojca.gov.ss")
LIST_PAGES = [
    "https://mojca.gov.ss/laws/",
    "https://www.mojca.gov.ss/laws/",
    "https://mojca.gov.ss/laws-of-the-republic-of-south-sudan/",
    "https://www.mojca.gov.ss/laws-of-the-republic-of-south-sudan/",
    "https://mojca.gov.ss/",
]


def allow_ocr() -> bool:
    return os.environ.get("ALLOW_OCR", "0") not in ("0", "false", "False", "", "no", "OFF")


def add_url(items, seen, url, prefer=False):
    url = (url or "").split("#")[0].replace(":80/", "/")
    if not url.startswith("http"):
        return
    low = url.lower()
    if not any(h in low for h in HOSTS):
        return
    if any(low.endswith(ext) or ext + "?" in low for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js")):
        return
    if any(x in low for x in ("logo", "banner", "brochure", "newsletter", "favicon", "wp-includes")):
        return
    is_pdf = low.endswith(".pdf") or ".pdf?" in low or "/uploads/" in low and ".pdf" in low
    # Keep law listing detail pages only if they look like documents
    if not is_pdf and not any(k in low for k in ("/laws/", "wp-content/uploads", "download", "document")):
        return
    if url.rstrip("/").endswith(("/laws", "/laws-of-the-republic-of-south-sudan")):
        return
    key = url.lower().rstrip("/")
    if key in seen:
        return
    seen.add(key)
    if is_pdf:
        stem = Path(unquote(url.split("?")[0])).stem
        ident = re.sub(r"[^\w.\-]+", "-", stem, flags=re.U).strip("-")[:160] or "ss-law"
    else:
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-").replace("?", "-")
        ident = unquote(ident)[:160]
    items.append((ident, url, 0 if (is_pdf or prefer) else 1))


def discover():
    items, seen = [], set()
    detail_pages = []

    for base in LIST_PAGES:
        for page in range(1, env_int("LIST_PAGES", 6) + 1):
            url = base if page == 1 else urljoin(base, f"page/{page}/")
            try:
                r = live_get(url, ua=UA, retries=1, verify=False)
            except Exception as exc:
                log.info("list %s %s", url, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            html = r.text or ""
            for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
                full = urljoin(url, href)
                low = full.lower()
                if low.endswith(".pdf") or (".pdf" in low and "wp-content/uploads" in low):
                    add_url(items, seen, full.split("?")[0], prefer=True)
                elif "/laws/" in low and full.rstrip("/") not in (
                    "https://mojca.gov.ss/laws", "https://www.mojca.gov.ss/laws",
                    "https://mojca.gov.ss/laws-of-the-republic-of-south-sudan",
                    "https://www.mojca.gov.ss/laws-of-the-republic-of-south-sudan",
                ):
                    detail_pages.append(full)
            if page >= 2 and ".pdf" not in html.lower() and "wp-content/uploads" not in html.lower():
                break

    dseen = set()
    details = []
    for d in detail_pages:
        k = d.lower().rstrip("/")
        if k not in dseen:
            dseen.add(k)
            details.append(d)
    details = details[: env_int("MAX_DETAIL", 80)]
    log.info("detail pages to follow %s", len(details))
    for durl in details:
        try:
            r = live_get(durl, ua=UA, retries=1, verify=False)
        except Exception:
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", flags=re.I):
            full = urljoin(durl, href)
            if ".pdf" in full.lower():
                add_url(items, seen, full.split("?")[0], prefer=True)

    for prefix in (
        "mojca.gov.ss/wp-content/uploads/",
        "www.mojca.gov.ss/wp-content/uploads/",
        "mojca.gov.ss/laws/",
        "www.mojca.gov.ss/laws/",
        "mojca.gov.ss/laws-of-the-republic-of-south-sudan/",
        "mojca.gov.ss/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 300), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add_url(items, seen, orig, prefer=True)
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and (".pdf" in orig.lower() or "/laws/" in orig.lower()):
                add_url(items, seen, orig)

    items.sort(key=lambda x: (x[2], x[1].lower()))
    out = [(i, u) for i, u, _ in items]
    log.info("catalog %s (prefer=%s)", len(out), sum(1 for _, _, r in items if r == 0))
    return out


def is_bad_en(text: str) -> bool:
    """English-law soft garbage check. Do NOT use Arabic-mojibake heuristic
    (is_garbage_text flags all Latin-heavy English as corrupt Arabic)."""
    if not text or len(text) < 80:
        return True
    if text.lstrip().startswith("%PDF") or "endobj" in text[:200]:
        return True
    if text.count("(cid:") >= 8:
        return True
    sample = text[:8000]
    letters = sum(ch.isalpha() for ch in sample)
    if letters < 80:
        return True
    # spaced-out OCR junk
    if sample.count(" ") > letters * 2.2 and letters < 200:
        return True
    return False


def recover_text(got: dict) -> tuple[str, str]:
    text = got.get("text") or ""
    method = got.get("method") or ""
    if text and not is_bad_en(text):
        return text, method
    if not allow_ocr():
        return text, method
    raw = got.get("content") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if raw and (raw[:4] == b"%PDF" or b"%PDF" in raw[:8192]):
        if raw[:4] != b"%PDF":
            raw = raw[raw.find(b"%PDF"):]
        new_text, how, _pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="eng",
            ocr_max_pages=env_int("OCR_PAGES", 30),
        )
        if new_text and not is_bad_en(new_text):
            return new_text, f"{method}+{how}" if method else how
    return text, method


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
        # Prefer PDFs this foothold; skip bare HTML listing shells
        if "/laws/" in url and ".pdf" not in url.lower() and "wp-content/uploads" not in url.lower():
            # Still try — some WP posts embed text; reject shells later
            pass
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
        if got.get("status") != "success" and not (got.get("content") or b""):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        text, method = recover_text(got)
        if not text or is_bad_en(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "garbage_or_short_text"})
            continue
        # Reject WP chrome / empty shells
        low_head = text[:600].lower()
        if ("ministry of justice" in low_head and len(text) < 800
                and text.count("Article") < 2 and text.count("Section") < 2):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "html_shell"})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ss.py",
            article_re=ART, extra_meta={"fetch_method": method},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], method, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="South Sudan MoJCA laws",
        source_urls=["https://mojca.gov.ss/laws/", "https://mojca.gov.ss/laws-of-the-republic-of-south-sudan/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (CDX/Wayback + live MoJCA law PDFs)",
        notes="Official MoJCA PDFs under wp-content/uploads. Article/Section splits. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
