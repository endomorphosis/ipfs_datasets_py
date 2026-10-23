#!/usr/bin/env python3
"""Paraguay: Biblioteca y Archivo del Congreso Nacional (BACN) leyes HTML."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "py", "Paraguay", "es"
SOURCE_TYPE = "bacn_congreso"
LICENSE = (
    "Official texts of laws of the Republic of Paraguay as published by the "
    "Biblioteca y Archivo del Congreso Nacional (bacn.gov.py). Gaceta Oficial / "
    "authentic congressional text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.bacn.gov.py/leyes-paraguayas)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
LIST = "https://www.bacn.gov.py/leyes-paraguayas"
log = logging.getLogger("py")


def discover() -> list[tuple[str, str]]:
    items, seen = [], set()
    def add(ident, url):
        if ident in seen:
            return
        seen.add(ident)
        items.append((ident, url))
    try:
        r = http_get(LIST, ua=UA, sleep=0.2)
        if r.status_code == 200:
            for href in re.findall(r'href="(https://www\.bacn\.gov\.py/leyes-paraguayas/\d+/[^"]+)"', r.text or ""):
                m = re.search(r"/leyes-paraguayas/(\d+)/", href)
                if m:
                    add(m.group(1), href.split("#")[0])
            for href in re.findall(r'href="(/leyes-paraguayas/\d+/[^"]+)"', r.text or ""):
                m = re.search(r"/leyes-paraguayas/(\d+)/", href)
                if m:
                    add(m.group(1), urljoin("https://www.bacn.gov.py/", href))
    except Exception as exc:
        log.info("list err %s", exc)
    for start in range(0, env_int("LIST_PAGES", 8) * 20, 20):
        try:
            r = http_get(f"{LIST}?start={start}", ua=UA, sleep=0.3)
            if r.status_code != 200:
                continue
            for href in re.findall(r'href="(https://www\.bacn\.gov\.py/leyes-paraguayas/\d+/[^"]+)"', r.text or ""):
                m = re.search(r"/leyes-paraguayas/(\d+)/", href)
                if m:
                    add(m.group(1), href.split("#")[0])
        except Exception:
            continue
    for h in cdx_urls("bacn.gov.py/leyes-paraguayas/", limit=env_int("CDX_LIMIT", 300), match_type="prefix"):
        orig = (h.get("original") or "").split("#")[0]
        m = re.search(r"/leyes-paraguayas/(\d+)/", orig)
        if m and ".pdf" not in orig.lower():
            add(m.group(1), orig.replace("http://", "https://"))
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
    items = discover()
    for ident, url in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
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
            if re.search(r"Ley\s+N", line, re.I) or (len(line.strip()) > 20 and "BACN" not in line):
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Ley BACN {ident}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_py.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s", ident)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="BACN leyes paraguayas",
        source_urls=["https://www.bacn.gov.py/leyes-paraguayas"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official BACN HTML. Not Gaceta Oficial bulk (TLS). Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
