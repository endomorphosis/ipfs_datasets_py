#!/usr/bin/env python3
"""Rwanda: Official Gazette PDFs from minijust.gov.rw file list."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, unquote, parse_qs, urlparse
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "rw", "Rwanda", "en"
SOURCE_TYPE = "minijust_official_gazette"
LICENSE = (
    "Official Gazette of the Republic of Rwanda (minijust.gov.rw). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.minijust.gov.rw/official-gazette)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.|Ingingo)\s+\d+[a-zA-Z]?)\b")
BASE = "https://www.minijust.gov.rw"
ROOT_GAZETTE = f"{BASE}/official-gazette"
log = logging.getLogger("rw")


def list_page(url: str) -> tuple[list[str], list[str]]:
    """Return (subdir_urls, pdf_urls) from a TYPO3 filelist page."""
    r = live_get(url, ua=UA, timeout=(20, 60))
    soup = BeautifulSoup(r.text or "", "html.parser")
    dirs, pdfs = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(strip=True) or "").strip()
        full = urljoin(BASE, href)
        if ".pdf" in href.lower():
            pdfs.append(full)
            continue
        if "tx_filelist_filelist" in href and "path" in href:
            if text in (".", "..", "Documents", "") or text.isdigit() or text.lower() in ("next", "prev", "..."):
                continue
            dirs.append(full)
    # Also absolute fileadmin / user_upload pdfs
    for m in re.findall(r'(?:https://www\.minijust\.gov\.rw)?(/fileadmin/[^"\']+\.pdf|/user_upload/[^"\']+\.pdf)', r.text or "", re.I):
        pdfs.append(urljoin(BASE, m))
    return dirs, list(dict.fromkeys(pdfs))


def discover():
    items, seen = [], set()
    # Start from root gazette index to get year folders
    try:
        r = live_get(ROOT_GAZETTE, ua=UA, timeout=(20, 60))
    except Exception as exc:
        log.info("root fail: %s", exc)
        return items
    soup = BeautifulSoup(r.text or "", "html.parser")
    year_urls = []
    for a in soup.find_all("a", href=True):
        if "tx_filelist_filelist" in a["href"] and "path" in a["href"]:
            t = a.get_text(strip=True)
            if t and any(y in t for y in ("2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018")):
                year_urls.append(urljoin(BASE, a["href"]))
    year_urls = list(dict.fromkeys(year_urls))[:10]
    log.info("year folders %s", len(year_urls))
    queue = list(year_urls)
    depth = 0
    while queue and depth < 80:
        depth += 1
        url = queue.pop(0)
        try:
            dirs, pdfs = list_page(url)
        except Exception as exc:
            log.info("list fail %s: %s", url[:80], exc)
            continue
        for d in dirs:
            if d not in seen and len(queue) < 120:
                queue.append(d)
        for pdf in pdfs:
            if pdf in seen:
                continue
            seen.add(pdf)
            # identity from filename
            name = unquote(Path(urlparse(pdf).path).name)
            ident = re.sub(r"\W+", "-", name.replace(".pdf", ""))[:160]
            items.append((ident, pdf))
            if len(items) >= env_int("PDF_LIMIT", 120):
                log.info("catalog pdfs %s", len(items))
                return items
    log.info("catalog pdfs %s", len(items))
    return items


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
        got = fetch_official(url, ua=UA, min_text=120)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 20:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_rw.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident[:70], len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="MINIJUST Official Gazette of Rwanda",
        source_urls=["https://www.minijust.gov.rw/official-gazette"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (filelist years/months)",
        notes="Official Gazette PDFs from MINIJUST. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
