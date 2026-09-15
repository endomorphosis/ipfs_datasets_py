#!/usr/bin/env python3
"""Afghanistan: MoJ Official Gazette PDFs + laws.moj.gov.af (Dari/fa primary).

CDX/Wayback of official hosts + live OfficialGazette / ShowLawPersian.
Package-only foothold. No Hub-upload. Not legal advice.
"""
from __future__ import annotations
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text, is_garbage_text, normalize_rtl_text

CC, COUNTRY, LANG = "af", "Afghanistan", "fa"
SOURCE_TYPE = "afg_moj_gazette"
LICENSE = (
    "Ministry of Justice of Afghanistan Official Gazette / laws.moj.gov.af. "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://laws.moj.gov.af/)"
# Article/Art/ماده/مادۀ/مادهٔ/مادة mid-line + digits OR spelled ordinals (اول/دوم/…)
# Digit form rejects glued Arabic letter (citations like ماده22قانون).
_ORD = (
    r"واحده|اولی?|اوله|اولى|دوم|دوهمه?|سومم?|سومی|چهارم|چارم|جارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم"
)
ART = re.compile(
    rf"(?im)((?:Article|Art\.?|المادة|ماد[هۀٔة]|مادة)\s*[-–—:．.]?\s*"
    rf"(?:\(\s*[0-9۰-۹٠-٩]{{1,4}}\s*\)|[0-9۰-۹٠-٩]{{1,4}}(?![0-9۰-۹٠-٩ء-يآأإؤئ])|(?:{_ORD})))"
)
log = logging.getLogger("af")
HOSTS = ("laws.moj.gov.af", "moj.gov.af", "www.moj.gov.af")
LIST_PAGES = [
    "http://laws.moj.gov.af/",
    "https://laws.moj.gov.af/",
    "https://moj.gov.af/",
    "https://www.moj.gov.af/",
    "https://moj.gov.af/content/files/OfficialGazette/",
    "https://www.moj.gov.af/content/files/OfficialGazette/",
]


def allow_ocr() -> bool:
    return os.environ.get("ALLOW_OCR", "0") not in ("0", "false", "False", "", "no", "OFF")


def add_url(items, seen, url):
    url = (url or "").split("#")[0].replace(":80/", "/")
    if not url.startswith("http"):
        return
    low = url.lower()
    if not any(h in low for h in HOSTS):
        return
    if any(low.endswith(ext) or ext + "?" in low for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js")):
        return
    if any(x in low for x in ("logo", "banner", "brochure", "form", "favicon")):
        return
    # Prefer PDFs / gazette / ShowLaw; keep ASPX law pages as secondary
    is_pdf = ".pdf" in low
    is_law = any(k in low for k in (
        "officialgazette", "showlaw", "showlawpersian", "content/files",
        "download", "gazett", "law.aspx", "laws.aspx",
    ))
    if not is_pdf and not is_law:
        return
    key = url.lower().rstrip("/")
    if key in seen:
        return
    seen.add(key)
    if is_pdf:
        stem = Path(unquote(url.split("?")[0])).stem
        ident = re.sub(r"[^\w.\-]+", "-", stem, flags=re.U).strip("-")[:160] or "af-gazette"
    else:
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-").replace("?", "-")
        ident = unquote(ident)[:160]
    items.append((ident, url, 0 if is_pdf else 1))


def discover():
    items, seen = [], set()

    # Live list / index pages for embedded PDFs and ShowLaw links
    for base in LIST_PAGES:
        try:
            r = live_get(base, ua=UA, retries=1, verify=False)
        except Exception as exc:
            log.info("list %s %s", base, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        html = r.text or ""
        for href in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', html, flags=re.I):
            full = urljoin(base, href)
            add_url(items, seen, full.split("?")[0] if ".pdf" in full.lower() else full)
        # also ShowLawPersian.aspx?id=N patterns in scripts
        for m in re.findall(r"ShowLawPersian\.aspx\?[^\"'\s<>]+", html, flags=re.I):
            add_url(items, seen, urljoin(base, m))

    for prefix in (
        "moj.gov.af/content/files/OfficialGazette/",
        "www.moj.gov.af/content/files/OfficialGazette/",
        "moj.gov.af/content/files/",
        "www.moj.gov.af/content/files/",
        "laws.moj.gov.af/",
        "moj.gov.af/",
        "www.moj.gov.af/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 400), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add_url(items, seen, orig)
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
            orig = h.get("original") or ""
            if not orig:
                continue
            low = orig.lower()
            if ".pdf" in low or "showlaw" in low or "officialgazette" in low or "content/files" in low:
                add_url(items, seen, orig)

    items.sort(key=lambda x: (x[2], x[1].lower()))
    out = [(i, u) for i, u, _ in items]
    log.info("catalog %s (pdfs=%s)", len(out), sum(1 for _, u, r in items if r == 0))
    return out


def recover_text(got: dict) -> tuple[str, str]:
    text = got.get("text") or ""
    method = got.get("method") or ""
    text = normalize_rtl_text(text)
    if text and not is_garbage_text(text) and len(text) >= 100:
        return text, method
    if not allow_ocr():
        return text, method
    raw = got.get("content") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if raw and (raw[:4] == b"%PDF" or b"%PDF" in raw[:8192]):
        if raw[:4] != b"%PDF":
            raw = raw[raw.find(b"%PDF"):]
        # fas tessdata available; ara as fallback script support
        new_text, how, _pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="fas+ara+eng",
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
        fa = sum(1 for ch in s if "\u0600" <= ch <= "\u06FF")
        if (fa >= 8 or len(s) > 24) and "(cid:" not in s and s.count("@") < 2:
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
        # Reject MoJ chrome / empty shells
        if "Ministry of Justice" in text[:300] and len(text) < 500 and "ماده" not in text:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "html_shell"})
            continue
        title = pick_title(text, ident, url)
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_af.py",
            article_re=ART, extra_meta={"fetch_method": method},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], method, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Afghanistan MoJ Official Gazette",
        source_urls=["http://laws.moj.gov.af/", "https://moj.gov.af/content/files/OfficialGazette/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (CDX/Wayback + live MoJ gazette PDFs)",
        notes="Official MoJ gazette/laws. Dari (fa) primary. fas OCR when text layer missing. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
