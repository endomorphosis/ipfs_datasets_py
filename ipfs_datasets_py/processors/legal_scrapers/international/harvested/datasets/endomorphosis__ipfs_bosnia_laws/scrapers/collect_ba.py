#!/usr/bin/env python3
"""Bosnia: Sluzbeni list BiH PdfDownload gazette issues (live + Wayback of official URLs)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode, urlunparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ba", "Bosnia and Herzegovina", "bs"
SOURCE_TYPE = "sluzbeni_list_bih"
LICENSE = (
    "Official Gazette of Bosnia and Herzegovina (Sluzbeni glasnik BiH / sluzbenilist.ba). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.sluzbenilist.ba/)"
ART = re.compile(r"(?m)^\s*((?:Član|Clan|Члан)\s+[0-9]+[a-zа-е]?)\b")
log = logging.getLogger("ba")
MAX_BYTES = 28 * 1024 * 1024  # stay under world_lib MAX_PDF comfort zone


def normalize_pdfdownload(url: str) -> str | None:
    low = (url or "").lower()
    if "sluzbenilist.ba" not in low and "sllist.ba" not in low:
        return None
    if "pdfdownload" not in low:
        return None
    p = urlparse(url.replace("http://", "https://").replace(":80/", "/").replace("&amp;", "&"))
    qs = {k.lower(): v for k, v in parse_qs(p.query).items()}
    broj = (qs.get("brojizdanja") or [None])[0]
    god = (qs.get("godinaizdanja") or [None])[0]
    nivo = (qs.get("nivoizdavanja_fk") or ["1"])[0]
    if not broj or not god:
        return None
    q = urlencode({"BrojIzdanja": broj, "NivoIzdavanja_FK": nivo, "GodinaIzdanja": god})
    host = "www.sluzbenilist.ba"
    return urlunparse(("https", host, "/page/PdfDownload", "", q, "")), f"sg-{god}-{nivo}-{broj}", (god, nivo, broj)


def discover():
    items, seen = [], set()

    def add(url, ts=None):
        got = normalize_pdfdownload(url)
        if not got:
            return
        canon, ident, key = got
        if key in seen:
            return
        seen.add(key)
        items.append((ident, canon, ts))

    # Live homepage / known recent issues (BiH nivo=1)
    try:
        r = live_get("https://www.sluzbenilist.ba/", ua=UA, timeout=(15, 40), verify=False)
        if r.status_code == 200 and r.text:
            for href in re.findall(r'/page/PdfDownload\?[^"\'>\s]+', r.text):
                add("https://www.sluzbenilist.ba" + href.replace("&amp;", "&"))
            for m in re.finditer(
                r'BrojIzdanja=(\d+).*?NivoIzdavanja_FK=(\d+).*?GodinaIzdanja=(\d+)',
                r.text.replace("&amp;", "&"),
            ):
                broj, nivo, god = m.group(1), m.group(2), m.group(3)
                add(f"https://www.sluzbenilist.ba/page/PdfDownload?BrojIzdanja={broj}&NivoIzdavanja_FK={nivo}&GodinaIzdanja={god}")
            # issue page links -> try PdfDownload for BiH (nivo 1) when we see broj/year
            for m in re.finditer(r'[Bb]roj\s+(\d+)\s*/\s*(\d{2,4})', r.text):
                broj, yy = m.group(1), m.group(2)
                god = yy if len(yy) == 4 else ("20" + yy if int(yy) < 50 else "19" + yy)
                add(f"https://www.sluzbenilist.ba/page/PdfDownload?BrojIzdanja={broj}&NivoIzdavanja_FK=1&GodinaIzdanja={god}")
    except Exception as exc:
        log.info("home err %s", exc)

    # CDX official PdfDownload (prefer PDF mime)
    for prefix in (
        "sluzbenilist.ba/page/PdfDownload",
        "www.sluzbenilist.ba/page/PdfDownload",
        "sllist.ba/page/PdfDownload",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 250),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        ):
            add(h.get("original") or "", h.get("timestamp"))
        # also HTML-labeled snapshots — some are actually PDFs mislabeled; keep small set
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 80), match_type="prefix"):
            orig = h.get("original") or ""
            if "NivoIzdavanja_FK=1" in orig or "nivoizdavanja_fk=1" in orig.lower():
                add(orig, h.get("timestamp"))

    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 50)
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
        # Size guard via HEAD before full download
        try:
            import requests
            from requests.packages.urllib3.exceptions import InsecureRequestWarning
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            hr = requests.head(url, timeout=(10, 20), headers={"User-Agent": UA}, verify=False, allow_redirects=True)
            cl = int(hr.headers.get("content-length") or 0)
            if cl and cl > MAX_BYTES:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"too_large:{cl}"})
                continue
        except Exception as exc:
            log.info("head skip %s %s", ident, exc)

        got = fetch_official(url, ua=UA, min_text=200, wayback_ts=ts, verify=False)
        text = got.get("text") or ""
        if got.get("status") != "success" or text.lstrip().startswith("%PDF"):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "bad_pdf", "ts": ts})
            continue
        if not any(k in text for k in ("Član", "ČLAN", "Zakon", "ZAKON", "Službeni", "glasnik", "Члан", "Odluk")):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_gazette_like"})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ba.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s bytes=%s", ident[:60], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Sluzbeni list BiH PdfDownload",
        source_urls=["https://www.sluzbenilist.ba/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (official PdfDownload; Docs portal login-walled; large issues skipped)",
        notes="Official gazette PdfDownload only. Forms/bookshop excluded. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
