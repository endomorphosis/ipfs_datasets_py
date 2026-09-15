#!/usr/bin/env python3
"""Montenegro: Sluzbeni list Crne Gore (sluzbenilist.me) + Wayback of official URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "me", "Montenegro", "sr"
SOURCE_TYPE = "sluzbeni_list_cg"
LICENSE = (
    "Official Gazette of Montenegro (Sluzbeni list Crne Gore, sluzbenilist.me). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.sluzbenilist.me/)"
ART = re.compile(r"(?m)^\s*((?:Član|Clan|Члан)\s+[0-9]+[a-zа-е]?)\b")
log = logging.getLogger("me")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if not url.startswith("http"):
            url = urljoin("https://www.sluzbenilist.me/", url)
        if url in seen or any(x in url.lower() for x in (".css", ".js", "/login", "facebook", "twitter")):
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(url)
        items.append((ident, url))
    try:
        r = http_get("https://www.sluzbenilist.me/", ua=UA, sleep=0.3)
        if r.status_code == 200:
            for href in re.findall(r'href="([^"]+)"', r.text or ""):
                if any(k in href.lower() for k in ("pdf", "propis", "sluzben", "broj", "akt", "zakon")):
                    add(href)
    except Exception as exc:
        log.info("home %s", exc)
    for prefix in (
        "sluzbenilist.me/SluzbeniListDetalji",
        "sluzbenilist.me/pregled",
        "www.sluzbenilist.me/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and (".pdf" in orig.lower() or "detalj" in orig.lower() or "propis" in orig.lower()):
                add(orig.replace("http://", "https://"))
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
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_me.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Sluzbeni list Crne Gore",
        source_urls=["https://www.sluzbenilist.me/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official gazette portal + Wayback of official URLs. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
