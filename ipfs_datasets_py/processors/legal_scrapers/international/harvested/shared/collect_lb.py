#!/usr/bin/env python3
"""Lebanon: Official Gazette (jo.pcm.gov.lb) PDFs + pcm.gov.lb DynamicFile docs.

Official hosts only: jo.pcm.gov.lb, pcm.gov.lb / www.pcm.gov.lb.
Live PCM DynamicFile + listingandpdf crawl; JO print-1desc live PDFs;
Wayback of official JO/PCM URLs when live fails (egazette fullAdad often login-walled).
No Adala/Qistas/commercial. Not legal advice.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

urllib3.disable_warnings()

CC, COUNTRY, LANG = "lb", "Lebanon", "ar"
SOURCE_TYPE = "jo_pcm_lebanon"
LICENSE = (
    "Official Gazette of the Lebanese Republic / Presidency of the Council of Ministers "
    "(jo.pcm.gov.lb, pcm.gov.lb). Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://jo.pcm.gov.lb/)"
ART = re.compile(r"(?im)^\s*((?:المادة|مادة|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("lb")

# Lean deepen: skip PPP / VNR / project English shells (Cap densify upside was ~0).
SHELL_TITLE = re.compile(
    r"(?i)(?:\bPPP\b|public[- ]private\s+partnership|voluntary\s+national\s+review|\bVNR\b|"
    r"infrastructure\s+projects?|transport\s+capital\s+investment|national\s+economic\s+vision|"
    r"scope\s+and\s+methodology|potential\s+ppp|cycles?\s+1\s*(?:&|and)\s*2|"
    r"estimated\s+cost\s*\(mus|high\s+council\s+for\s+privatization)"
)
LAWISH_URL = re.compile(
    r"(?i)(?:print-1desc|egazette|fulladad|/pdfs/|jarida|gazette|decree|decrets?|"
    r"qarar|قانون|مرسوم|جريد)"
)

def is_shell_doc(title: str, text: str, url: str = "") -> bool:
    head = ((title or "") + "\n" + (text or "")[:1200])
    if SHELL_TITLE.search(head):
        return True
    # English project decks: long Latin, almost no Arabic legal markers
    sample = (text or "")[:2500]
    if not sample:
        return False
    ar = sum(1 for ch in sample if "\u0600" <= ch <= "\u06ff")
    if ar < 40 and SHELL_TITLE.search(sample):
        return True
    if ar < 20 and not LAWISH_URL.search(url or "") and "print-1desc" not in (url or "").lower():
        # thin latin-only DynamicFile without gazette cues
        if re.search(r"(?i)\b(?:project|investment|vision|review|methodology)\b", sample):
            return True
    return False

def prefer_key(ident: str, url: str) -> tuple:
    low = (url or "").lower()
    ident = ident or ""
    # lower is better
    if ident.startswith("jo-") or "print-1desc" in low or "egazette" in low or "fulladad" in low:
        return (0, ident)
    if "/pdfs/" in low or LAWISH_URL.search(low):
        return (1, ident)
    return (2, ident)


SEED_LISTING_PAGEIDS = (
    44, 21173, 11224, 11231, 11232, 11233, 11234, 11305, 11371,
    13090, 13537, 13560, 13587, 18198, 21198, 22330, 22469,
    10, 11, 12, 16, 17, 18, 21, 22,
)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    url = url.replace("http://", "https://").replace(":80/", "/")
    # collapse truncated published= stubs from CDX into published=1
    if "DynamicFile.aspx" in url and "PageID=" in url:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=True)
        page = (qs.get("PageID") or qs.get("pageid") or [None])[0]
        ph = (qs.get("PHName") or ["Document"])[0] or "Document"
        if page and page.isdigit():
            q = urlencode({"PHName": ph, "PageID": page, "published": "1"})
            url = urlunparse(("https", "www.pcm.gov.lb", "/Admin/DynamicFile.aspx", "", q, ""))
    return url


def _ok_host(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in ("jo.pcm.gov.lb", "pcm.gov.lb"))


def discover_live_pcm(session: requests.Session) -> list[tuple[str, str]]:
    items, seen_url, seen_pid = [], set(), set()
    queue = list(SEED_LISTING_PAGEIDS)
    max_pages = env_int("LB_MAX_LISTING_PAGES", 80)

    def add(url: str):
        url = _norm_url(url)
        if not _ok_host(url):
            return
        low = url.lower()
        if "dynamicfile" not in low and ".pdf" not in low and "print-1desc" not in low:
            return
        if url in seen_url:
            return
        if "dynamicfile" in low:
            m = re.search(r"PageID=(\d+)", url, re.I)
            ident = f"pcm-{m.group(1)}" if m else Path(url.split("?")[0]).name[:80]
        elif "print-1desc" in low:
            m = re.search(r"id=(\d+)", url, re.I)
            ident = f"jo-{m.group(1)}" if m else "jo-print"
        else:
            ident = Path(url.split("?")[0]).stem[:160]
        seen_url.add(url)
        items.append((ident, url))

    while queue and len(seen_pid) < max_pages:
        pid = queue.pop(0)
        if pid in seen_pid:
            continue
        seen_pid.add(pid)
        url = f"https://www.pcm.gov.lb/arabic/listingandpdf.aspx?pageid={pid}"
        try:
            time.sleep(0.2)
            r = session.get(url, timeout=40, verify=False, allow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text or ""
        except Exception as exc:
            log.info("listing fail %s: %s", pid, exc)
            continue
        for href in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', html, re.I):
            full = urljoin(url, href)
            if "DynamicFile" in full or ".pdf" in full.lower() or "print-1desc" in full.lower():
                add(full)
        for child in re.findall(r"pageid=(\d+)", html, re.I):
            c = int(child)
            if c not in seen_pid and c not in queue and len(queue) < 200:
                queue.append(c)
        log.info("listing pageid=%s docs_so_far=%s queue=%s", pid, len(items), len(queue))
    return items


def discover_cdx() -> list[tuple[str, str]]:
    items, seen = [], set()

    def add(url: str):
        url = _norm_url(url)
        if not _ok_host(url):
            return
        low = url.lower()
        if ".pdf" not in low and "dynamicfile" not in low and "print-1desc" not in low:
            return
        if "print-1desc.php" in low and "id=" not in low:
            return
        if url in seen:
            return
        if "dynamicfile" in low:
            m = re.search(r"PageID=(\d+)", url, re.I)
            if not m:
                return
            ident = f"pcm-{m.group(1)}"
        elif "print-1desc" in low:
            m = re.search(r"id=(\d+)", url, re.I)
            ident = f"jo-{m.group(1)}" if m else "jo-print"
        elif "fulladad" in low:
            ident = "jo-issue-" + Path(url.split("?")[0]).stem[:80]
        else:
            ident = Path(url.split("?")[0]).stem[:160]
        # dedupe by ident preference: keep first
        for i, u in items:
            if i == ident:
                return
        seen.add(url)
        items.append((ident, url))

    prefixes = (
        "jo.pcm.gov.lb/egazette_png/",
        "jo.pcm.gov.lb/pdfs/",
        "jo.pcm.gov.lb/pdfs/print-1desc.php",
        "www.pcm.gov.lb/Admin/DynamicFile.aspx",
        "pcm.gov.lb/Admin/DynamicFile.aspx",
        "www.pcm.gov.lb/",
    )
    lim = env_int("CDX_LIMIT", 400)
    for prefix in prefixes:
        for h in cdx_urls(prefix, limit=lim, match_type="prefix"):
            orig = h.get("original") or ""
            if orig:
                add(orig)
        for h in cdx_urls(
            prefix, limit=lim, match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    return items


def discover() -> list[tuple[str, str]]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
    live = discover_live_pcm(session)
    cdx = discover_cdx()
    by_ident = {}
    # prefer live DynamicFile / print URLs
    for ident, url in cdx + live:
        by_ident[ident] = url
    items = list(by_ident.items())
    log.info("catalog live=%s cdx=%s merged=%s", len(live), len(cdx), len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    catalog = discover()
    catalog = sorted(catalog, key=lambda it: prefer_key(it[0], it[1]))
    for ident, url in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=100)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 10:
                title = line.strip()[:240]
                break
        if is_shell_doc(title or "", text, url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "shell_ppp_vnr_project",
                             "title": (title or "")[:120]})
            log.info("skip shell %s", ident[:70])
            continue
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_lb.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Lebanon Official Gazette / PCM",
        source_urls=["https://jo.pcm.gov.lb/", "https://www.pcm.gov.lb/"],
        license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live PCM DynamicFile + Wayback of official JO/PCM PDFs)",
        notes=(
            "Official gazette/PCM PDFs only. Live jo.pcm.gov.lb egazette_png often login-walled; "
            "print-1desc and pcm.gov.lb DynamicFile used live when available. Arabic OCR may be thin. "
            "Lean deepen: prefer JO/decree/gazette PDFs; skip PPP/VNR/project shells. Not Adala/Qistas. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(catalog))


if __name__ == "__main__":
    main()
