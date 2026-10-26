#!/usr/bin/env python3
"""Serbia: PIS viewdoc PDFs (Wayback) + National Assembly official zakoni PDFs (parlament.gov.rs)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode, urlunparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "rs", "Serbia", "sr"
SOURCE_TYPE = "pis_parlament_pdf"
LICENSE = (
    "Official Gazette of the Republic of Serbia / Legal Information System "
    "(pravno-informacioni-sistem.rs) and National Assembly (parlament.gov.rs). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://pravno-informacioni-sistem.rs/)"
ART = re.compile(r"(?m)^\s*((?:Члан|Član)\s+[0-9]+[а-еa-z]?)\b")
log = logging.getLogger("rs")


def to_pdf_url(url: str) -> str | None:
    low = url.lower()
    if "pravno-informacioni-sistem.rs" not in low:
        return None
    if "viewdoc" not in low and "findpdfurl" not in low:
        return None
    p = urlparse(url.replace("http://", "https://").replace(":80/", "/"))
    qs = parse_qs(p.query)
    rid = (qs.get("regactid") or qs.get("RegActId") or [None])[0]
    if not rid:
        return None
    q = urlencode({"regactid": rid, "doctype": "reg", "findpdfurl": "true"})
    return urlunparse((p.scheme or "https", p.netloc.replace(":80", ""), "/SlGlasnikPortal/viewdoc", "", q, ""))


def discover():
    items, seen = [], set()

    def add(ident, url, ts=None):
        if not url or ident in seen or url in seen:
            return
        seen.add(ident)
        seen.add(url)
        items.append((ident, url, ts))

    # 1) PIS viewdoc PDF snapshots
    for prefix in (
        "www.pravno-informacioni-sistem.rs/SlGlasnikPortal/viewdoc",
        "pravno-informacioni-sistem.rs/SlGlasnikPortal/viewdoc",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 250),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            pdf = to_pdf_url(orig)
            if pdf:
                rid = parse_qs(urlparse(pdf).query).get("regactid", [""])[0]
                add(f"regact-{rid}", pdf, h.get("timestamp"))

    # 2) National Assembly adopted laws PDFs (official)
    for prefix in (
        "www.parlament.gov.rs/upload/archive/files/cir/pdf/zakoni/",
        "parlament.gov.rs/upload/archive/files/cir/pdf/zakoni/",
        "www.parlament.gov.rs/upload/archive/files/lat/pdf/zakoni/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 200),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        ):
            orig = (h.get("original") or "").replace("http://", "https://").replace(":80/", "/")
            if not orig.lower().endswith(".pdf"):
                continue
            # Prefer adopted laws over predlozi if path distinguishes; keep zakoni folder
            if "predlozi" in orig.lower():
                continue
            stem = Path(unquote(urlparse(orig).path)).stem
            add(f"parlament-{stem}"[:160], orig, h.get("timestamp"))

    # Prefer parlament first (live works) then PIS
    items.sort(key=lambda x: (0 if x[0].startswith("parlament-") else 1, x[0]))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success" or len(text) < 200:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "too_short", "ts": ts})
            continue
        if not any(k in text for k in ("Члан", "Član", "ЗАКОН", "Zakon", "УСТАВ", "ZAKON")):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_law_like"})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 12:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_rs.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="PIS viewdoc PDF + parlament.gov.rs zakoni",
        source_urls=[
            "https://www.pravno-informacioni-sistem.rs/",
            "https://www.parlament.gov.rs/upload/archive/files/cir/pdf/zakoni/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (PIS Wayback PDFs + National Assembly official law PDFs)",
        notes="Official PIS/Assembly only. Live PIS is SPA; CDX PDF timestamps used. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
