#!/usr/bin/env python3
"""Armenia: official ARLIS (Pashtonakan teghekagir / Ministry of Justice)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, html_to_text, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log

CC, COUNTRY, LANG = "am", "Armenia", "hy"
SOURCE_TYPE = "arlis"
LICENSE = (
    "Official regulatory legal acts of the Republic of Armenia as published on "
    "ARLIS (arlis.am) by Pashtonakan teghekagir CJSC under the Ministry of Justice "
    "(Law on Regulatory Legal Acts, Art. 25). Official ARLIS text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.arlis.am/)"
ART = re.compile(r"(?m)^\s*((?:Հոդված|ՀՈԴՎԱԾ|Article|Статья)\s+[0-9]+[A-Za-zԱ-Ֆա-ֆ]?)\b")
log = logging.getLogger("am")
SEED = [20, 29, 39, 41, 49, 51, 105967, 143723, 145009, 152139]


def discover() -> list[tuple[str, str, str]]:
    items, seen = [], set()
    def add(i, url):
        i = str(i)
        if i in seen:
            return
        seen.add(i)
        items.append((i, url, None))
    try:
        r = http_get("https://www.arlis.am/hy/", ua=UA, sleep=0.2)
        if r.status_code == 200:
            for i in re.findall(r"/acts/(\d+)", r.text or ""):
                add(i, f"https://www.arlis.am/hy/acts/{i}/latest")
    except Exception as exc:
        log.info("home err %s", exc)
    for i in SEED:
        add(i, f"https://www.arlis.am/hy/acts/{i}/latest")
    for h in cdx_urls("arlis.am/hy/acts/", limit=env_int("CDX_LIMIT", 250), match_type="prefix"):
        orig = h.get("original") or ""
        m = re.search(r"/acts/(\d+)", orig)
        if m:
            add(m.group(1), f"https://www.arlis.am/hy/acts/{m.group(1)}/latest")
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
    for ident, url, _ in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        from world_lib import slug_id
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
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"ARLIS act {ident}", text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_am.py", article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s bytes=%s method=%s", ident, len(text), got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="ARLIS arlis.am",
        source_urls=["https://www.arlis.am/"], license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official ARLIS HTML (live; Wayback of official URLs on failure). Codes + recent acts. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
