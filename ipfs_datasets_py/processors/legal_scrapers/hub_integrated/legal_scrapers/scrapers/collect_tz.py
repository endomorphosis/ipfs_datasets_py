#!/usr/bin/env python3
"""Tanzania: OAG MIS portal acts (acts-ajax catalog + /portal/acts/{id}/download PDFs)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "tz", "Tanzania", "en"
SOURCE_TYPE = "oagmis_acts"
LICENSE = (
    "Acts of the Parliament of the United Republic of Tanzania as published on "
    "oagmis.oag.go.tz / parliament.go.tz. Government Printer gazette text prevails. "
    "Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://oagmis.oag.go.tz/)"
ART = re.compile(r"(?im)^\s*((?:Section|Article|Part)\s+[0-9IVXLC]+)\b")
log = logging.getLogger("tz")


def discover():
    items, seen = [], set()

    def add(ident, url, meta=None):
        if not url or url in seen:
            return
        seen.add(url)
        items.append((ident, url, meta or {}))

    # Primary: live OAG MIS DataTables ajax (official AG portal)
    try:
        r = http_get(
            "https://oagmis.oag.go.tz/portal/acts-ajax?draw=1&start=0&length=400",
            ua=UA, sleep=0.3, timeout=(15, 60),
        )
        if r.status_code == 200:
            data = r.json().get("data") or []
            log.info("acts-ajax rows %s", len(data))
            for row in data:
                aid = row.get("id")
                if not aid:
                    continue
                title = (row.get("shortTitle") or row.get("longTitle") or f"act-{aid}").strip()
                add(
                    f"act-{aid}",
                    f"https://oagmis.oag.go.tz/portal/acts/{aid}/download",
                    {"title": title, "enactment": row.get("enactmentNo"), "pub": row.get("publicationDate")},
                )
        else:
            log.info("acts-ajax HTTP %s", r.status_code)
    except Exception as exc:
        log.info("acts-ajax err %s", exc)

    # Fallback: CDX of official download endpoints
    for prefix in (
        "oagmis.oag.go.tz/portal/acts/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 120), match_type="prefix"):
            orig = h.get("original") or ""
            if "/download" in orig.lower():
                m = re.search(r"/acts/(\d+)/download", orig)
                ident = f"act-{m.group(1)}" if m else re.sub(r"^https?://[^/]+/", "", orig).replace("/", "-")[:160]
                add(ident, orig.replace("http://", "https://"), {"ts": h.get("timestamp")})

    # Secondary: parliament.go.tz asset PDFs (acts/bills) via CDX — skip if we already have plenty
    if len(items) < 20:
        for prefix in (
            "www.parliament.go.tz/assets/uploads/files/",
            "parliament.go.tz/assets/uploads/files/",
        ):
            for h in cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 80),
                match_type="prefix",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            ):
                orig = h.get("original") or ""
                low = orig.lower()
                if any(k in low for k in ("act", "bill", "finance", "written", "law")):
                    ident = Path(urlparse_path(orig)).stem[:160]
                    add(ident, orig, {"ts": h.get("timestamp")})

    log.info("catalog %s", len(items))
    return items


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).path


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, meta in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        ts = meta.get("ts")
        got = fetch_official(url, ua=UA, min_text=150, wayback_ts=ts, verify=False)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Prefer statute-like text
        if not any(k in text for k in ("Section", "PART", "Act", "ACT", "United Republic", "Tanzania")):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_act_like"})
            continue
        title = meta.get("title")
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_tz.py",
            date=meta.get("pub"),
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "enactment": meta.get("enactment")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="OAG MIS Acts of Parliament",
        source_urls=["https://oagmis.oag.go.tz/portal/acts", "https://www.parliament.go.tz/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (OAG MIS acts-ajax + official PDF downloads)",
        notes="Official OAG/Bunge only. Not tanzanialaws.com. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
