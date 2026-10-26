#!/usr/bin/env python3
"""Rwanda: official Official Gazette / laws PDFs via minijust.gov.rw / primature.gov.rw / parliament.gov.rw / rlrc.gov.rw.

Official *.gov.rw only. Not AfricanLII / RwandaLII / gazettes.africa as source text.
No WAF bypass. Live-first; Wayback/CDX of official URLs OK (pass CDX timestamps).
"""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "rw", "Rwanda", "en"
SOURCE_TYPE = "rwanda_official_gazette_laws"
LICENSE = (
    "Republic of Rwanda — Ministry of Justice (minijust.gov.rw) / Primature (primature.gov.rw) / "
    "Parliament (parliament.gov.rw) / Rwanda Law Reform Commission (rlrc.gov.rw) and other *.gov.rw "
    "Official Gazette hosts. Authentic Official Gazette / Law text prevails. "
    "Not AfricanLII / RwandaLII / gazettes.africa. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.minijust.gov.rw/)"
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Chapter|Chapitre|Ingingo)\s*[0-9]+)\b"
)
log = logging.getLogger("rw")
HOMES = [
    "https://www.minijust.gov.rw/laws",
    "https://www.minijust.gov.rw/official-gazette",
    "https://www.minijust.gov.rw/",
    "https://www.primature.gov.rw/",
    "https://www.parliament.gov.rw/",
    "https://www.rlrc.gov.rw/",
    "https://rlrc.gov.rw/",
    "https://www.gov.rw/",
]
ALLOWED = ("gov.rw",)
DROP_RE = re.compile(
    r"(africanlii|rwandalii|gazettes\.africa|law\.africa|/news/|/videos?/|interview|"
    r"facebook|youtube|twitter|logo|banner|photo|recruitment|vacancy|newsletter|"
    r"tender|procurement|job[_-]?announcement|press[_-]?release|discours|"
    r"strategic.?plan|annual.?report|brochure|flyer|calendar|factsheet|"
    r"application.?form|itangazo|announcement|SPEECHES|_ppt_)",
    re.I,
)
KEEP_RE = re.compile(
    r"(official.?gazette|\bOG[_\s]|gazette|igazeti|law|loi|decree|arr[eê]t[eé]|constitution|"
    r"organic.?law|presidential.?order|ministerial.?order|prime.?minister|"
    r"instruction|code|statute|legislation|proclamation|ingingo|"
    r"abunzi|offences|penalties|whistle|fileadmin.*(Laws|Gazette|OG|Legal|Igazeti))",
    re.I,
)
MAX_PDF_BYTES = 12 * 1024 * 1024


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "rwandalii", "gazettes.africa", "law.africa")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    url = re.sub(r"(https?://[^/:]+):80/", r"\1/", url)
    return url


def _laws_page_urls(base: str = "https://www.minijust.gov.rw/laws", pages: int = 10) -> list[str]:
    out = [base]
    for n in range(2, pages + 1):
        out.append(
            f"{base}?tx_filelist_filelist%5Bcontroller%5D=File&tx_filelist_filelist%5BcurrentPage%5D={n}"
        )
    return out


def discover():
    """Return list of (ident, url, wayback_ts|None). Live homes first; CDX with timestamps."""
    items = []  # (priority, ident, url, ts)
    seen = set()

    def add(url: str, ts: str | None = None, priority: int = 50):
        url = _norm_url(url)
        if not url.startswith("http"):
            return
        if not _host_ok(url) or DROP_RE.search(url):
            return
        if ".pdf" not in url.lower():
            return
        blob = unquote(url)
        if not KEEP_RE.search(blob):
            if not re.search(
                r"(?i)/(Publications?/Laws|Official.?Gazette|Official_gazettes|Igazeti|"
                r"fileadmin.*(Laws|OG|Gazette|Legal)|/laws/)",
                blob,
            ):
                return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        ident = re.sub(r"^https?://[^/]+/", "", unquote(url)).replace("/", "-").replace("?", "-")[:160]
        items.append((priority, ident, url, ts))

    homes = list(HOMES) + _laws_page_urls(pages=env_int("RW_LAWS_PAGES", 10))
    for n in range(2, 6):
        homes.append(
            f"https://www.minijust.gov.rw/official-gazette?"
            f"tx_filelist_filelist%5Bcontroller%5D=File&tx_filelist_filelist%5BcurrentPage%5D={n}"
        )

    for home in homes:
        try:
            r = http_get(home, ua=UA, sleep=0.25)
            if getattr(r, "status_code", 0) != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
                add(urljoin(home, href.replace("&amp;", "&")), ts=None, priority=10)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    cdx_prefixes = (
        "www.minijust.gov.rw/fileadmin/user_upload/Minijust/Publications/Laws/",
        "www.minijust.gov.rw/fileadmin/user_upload/Minijust/Official_gazettes",
        "minijust.gov.rw/fileadmin/user_upload/Minijust/Publications/Laws/",
        "minijust.gov.rw/fileadmin/user_upload/Minijust/Official_gazettes",
        "www.primature.gov.rw/fileadmin/user_upload/documents/Official",
        "primature.gov.rw/fileadmin/user_upload/documents/Official",
        "rlrc.gov.rw/fileadmin/",
        "www.rlrc.gov.rw/fileadmin/",
        "www.parliament.gov.rw/fileadmin/",
        "parliament.gov.rw/fileadmin/",
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 200),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        for h in hits:
            orig = h.get("original") or ""
            ts = (h.get("timestamp") or "")[:14] or None
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            pri = 20
            if re.search(r"(?i)official.?gazette|igazeti|/Laws/|Publications/Laws", unquote(orig)):
                pri = 15
            add(orig, ts=ts, priority=pri)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts) for _, ident, url, ts in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    ok = skip = fail = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=200, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_rw.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s ts=%s", ident[:60], got.get("method"), len(text), ts)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="Rwanda Official Gazette / laws (minijust.gov.rw / primature.gov.rw / parliament.gov.rw / rlrc.gov.rw)",
        source_urls=[
            "https://www.minijust.gov.rw/laws",
            "https://www.minijust.gov.rw/official-gazette",
            "https://www.primature.gov.rw/",
            "https://www.parliament.gov.rw/",
            "https://www.rlrc.gov.rw/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (PDF-first live+CDX *.gov.rw with timestamps)",
        notes="Official *.gov.rw PDFs only. Not AfricanLII/RwandaLII/gazettes.africa. No WAF bypass. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
