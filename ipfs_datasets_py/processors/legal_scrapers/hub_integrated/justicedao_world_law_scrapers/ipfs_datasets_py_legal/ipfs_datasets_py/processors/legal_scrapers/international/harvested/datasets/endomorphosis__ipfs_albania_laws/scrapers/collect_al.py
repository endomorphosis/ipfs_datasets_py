#!/usr/bin/env python3
"""Albania: Official Fletorja Zyrtare PDFs from QPZ (predecessor of QBZ) + QBZ Alfresco content via Wayback."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "al", "Albania", "sq"
SOURCE_TYPE = "qbz_fletore_pdf"
LICENSE = (
    "Official acts of the Republic of Albania as published by Qendra e Botimeve Zyrtare / "
    "Qendra e Publikimeve Zyrtare (qbz.gov.al / qpz.gov.al, Fletorja Zyrtare). "
    "Authentic FZ text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.qbz.gov.al/)"
ART = re.compile(r"(?m)^\s*((?:Neni|NENI|Article)\s+[0-9]+[A-Za-z]?)\b")
log = logging.getLogger("al")


def discover():
    """Prefer static official gazette PDFs (qpz botime) and QBZ Alfresco /content PDFs."""
    items, seen = [], set()

    def add(url, ts=None, kind="pdf"):
        url = (url or "").replace(":80/", "/").split("#")[0]
        if not url or url in seen:
            return
        low = url.lower()
        if kind == "pdf" and ".pdf" not in low and "/content" not in low:
            return
        if any(x in low for x in (".css", ".js", "/renditions/", "tracemonkey", "english/")):
            return
        # skip English translations folder sometimes present under botime/English
        path = urlparse(url).path
        ident = re.sub(r"[^a-zA-Z0-9._-]+", "-", path.strip("/"))[:160]
        if not ident or ident in seen:
            return
        seen.add(url)
        seen.add(ident)
        items.append((ident, url if url.startswith("http") else "http://" + url, ts))

    # Historic official static PDF gazette path (QPZ = official publisher, now QBZ)
    for prefix in (
        "qpz.gov.al/botime/fletore_zyrtare/",
        "www.qpz.gov.al/botime/fletore_zyrtare/",
        "qpz.gov.al/botime/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 300),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        ):
            add(h.get("original") or "", h.get("timestamp"))

    # QBZ Alfresco node content PDFs (official portal storage)
    for prefix in (
        "qbz.gov.al/alfresco/api/-default-/public/alfresco/versions/1/nodes/",
        "www.qbz.gov.al/alfresco/api/-default-/public/alfresco/versions/1/nodes/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 150),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        ):
            orig = h.get("original") or ""
            if "/content" in orig.lower():
                add(orig, h.get("timestamp"))

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
        got = fetch_official(url, ua=UA, verify=False, min_text=150, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "ts": ts})
            continue
        # Prefer Fletore / Ligj markers when present; still keep gazette issues
        markers = ("FLETORJA", "Fletorja", "Neni", "NENI", "LIGJ", "Ligj", "REPUBLIK")
        if not any(m in text for m in markers) and len(text) < 500:
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_al.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="QBZ/QPZ Fletorja Zyrtare PDFs",
        source_urls=["https://www.qbz.gov.al/", "http://www.qpz.gov.al/botime/fletore_zyrtare/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official QPZ FZ PDFs + QBZ Alfresco content; live Angular shell)",
        notes="Official QPZ/QBZ only. No unofficial bazaligjore. ELI SPA skipped. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
