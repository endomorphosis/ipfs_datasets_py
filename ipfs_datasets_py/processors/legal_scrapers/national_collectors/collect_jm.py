#!/usr/bin/env python3
"""Jamaica: Laws of Jamaica official PDFs (MOJ laws/ + laws.moj.gov.jm)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "jm", "Jamaica", "en"
SOURCE_TYPE = "moj_jamaica"
LICENSE = "Laws of Jamaica — Ministry of Justice / Parliament. Authentic text prevails. Not legal advice."
UA = "legal-corpora-collector/1.0 (research; source=https://moj.gov.jm/)"
ART = re.compile(r"(?im)^\s*((?:Section|s\.|PART)\s+[IVXLC\d]+[A-Za-z]?\.?)\b")
log = logging.getLogger("jm")

SKIP_RE = re.compile(
    r"(advert|vacan|career|brochure|job[\s_-]?desc|justice[_\s-]?of[_\s-]?the[_\s-]?peace|"
    r"active[_\s-]?justices|/careers/|/brochures/|expungement%20brochure|standing%20orders|"
    r"ministry%20paper|sectoral|statement-trafigura|cpo-jd|corporate%20communication)",
    re.I,
)
KEEP_RE = re.compile(
    r"(laws?/|legislation/|/docs/|Act|Regs?\.|Regulations|Order|Statute|Constitution|Rules)",
    re.I,
)

def _ident_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0]).rstrip("/")).stem
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:140] or "jm-doc"

def _is_law_pdf(url: str) -> bool:
    u = url or ""
    if ".pdf" not in u.lower():
        return False
    if SKIP_RE.search(u):
        return False
    # Prefer known law path prefixes
    low = u.lower()
    if any(p in low for p in (
        "/sites/default/files/laws/",
        "laws.moj.gov.jm/legislation/",
        "/sites/default/files/docs/",
    )):
        return True
    if "moj.gov.jm" in low or "laws.moj.gov.jm" in low:
        return bool(KEEP_RE.search(u))
    if "japarliament.gov.jm" in low and "act" in low:
        return True
    return False

def _cdx_http(prefix: str, limit: int = 250) -> list[str]:
    """CDX via http://web.archive.org (https CDX currently SSLEOF)."""
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    out = []
    try:
        r = requests.get(
            "http://web.archive.org/cdx/search/cdx",
            params={
                "url": prefix,
                "output": "json",
                "fl": "original,timestamp,statuscode,mimetype",
                "limit": limit,
                "matchType": "prefix",
                "filter": "mimetype:application/pdf",
                "collapse": "urlkey",
            },
            timeout=90,
        )
        if r.status_code != 200:
            log.info("cdx_http status %s %s", r.status_code, prefix)
            return out
        rows = r.json()
        for row in rows[1:]:
            out.append(row[0])
    except Exception as exc:
        log.info("cdx_http fail %s: %s", prefix, exc)
    return out

def discover():
    items, seen = [], set()
    # Cached URL list from prior CDX harvest (fast path)
    cache = Path(str(_SCRAPERS) + "/tmp/jm_law_urls.txt")
    if cache.exists():
        for line in cache.read_text().splitlines():
            url = line.strip().replace("http://", "https://")
            if not url or url in seen or not _is_law_pdf(url):
                continue
            seen.add(url)
            items.append((_ident_from_url(url), url))
        log.info("cache urls %s", len(items))
    seeds = [
        "https://moj.gov.jm/laws",
        "https://laws.moj.gov.jm/library",
        "https://laws.moj.gov.jm/",
    ]
    for su in seeds:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text or "", re.I):
            url = urljoin(su, href).replace("http://", "https://")
            if url in seen or not _is_law_pdf(url):
                continue
            seen.add(url)
            items.append((_ident_from_url(url), url))
    prefixes = [
        "moj.gov.jm/sites/default/files/laws/",
        "www.moj.gov.jm/sites/default/files/laws/",
        "laws.moj.gov.jm/legislation/",
        "moj.gov.jm/sites/default/files/docs/",
    ]
    cdx_limit = env_int("CDX_LIMIT", 250)
    for prefix in prefixes:
        # Prefer http CDX; fall back to shared helper
        for orig in _cdx_http(prefix, cdx_limit):
            orig = orig.replace("http://", "https://")
            orig = re.sub(r":80/", "/", orig)
            if not orig or orig in seen or not _is_law_pdf(orig):
                continue
            seen.add(orig)
            items.append((_ident_from_url(orig), orig))
    log.info("catalog %s", len(items))
    return items

def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Reject job-ad / brochure bodies that slipped through
        head = (text[:800] + " " + ident).lower()
        if SKIP_RE.search(head) and not re.search(r"\b(act|regulation|order|statute)\b", head):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "non_law_filtered"})
            continue
        title = next((ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18), ident)
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_jm.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident[:60], len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="MOJ Jamaica / Laws of Jamaica",
        source_urls=["https://moj.gov.jm/", "https://laws.moj.gov.jm/", "https://japarliament.gov.jm/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (MOJ laws/ + laws.moj legislation PDFs)",
        notes="Official Jamaican government law PDFs; careers/adverts filtered. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)

if __name__ == "__main__":
    main()
