#!/usr/bin/env python3
"""Uzbekistan: lex.uz official legislation HTML documents."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "uz", "Uzbekistan", "uz"
SOURCE_TYPE = "lex_uz"
LICENSE = (
    "Lex.uz — National Legal Information Database of Uzbekistan (Ministry of Justice). "
    "Official texts prevail. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://lex.uz/)"
ART = re.compile(
    r"(?im)^\s*((?:Статья|Modda|Article|ст\.)\s+\d+[^\n]{0,40})\b"
)
# Seed major codes / known docs; extend via search
SEED_DOCS = [
    ("111457", "Уголовный кодекс"),
    ("111189", "Фуқаролик кодекси / Гражданский кодекс"),
    ("145261", "Трудовой кодекс"),
]
SEARCHES = [
    "https://lex.uz/ru/search/nat?query=%D0%BA%D0%BE%D0%B4%D0%B5%D0%BA%D1%81&search_type=1",
    "https://lex.uz/search/nat?query=kodeks&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%B7%D0%B0%D0%BA%D0%BE%D0%BD&search_type=1",
    "https://lex.uz/search/nat?query=konstitutsiya&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%BD%D0%B0%D0%BB%D0%BE%D0%B3%D0%BE%D0%B2%D1%8B%D0%B9&search_type=1",
]
log = logging.getLogger("uz")


def discover():
    items, seen = [], set()
    for did, title in SEED_DOCS:
        if did not in seen:
            seen.add(did)
            items.append((did, f"https://lex.uz/docs/{did}", title))
    for surl in SEARCHES:
        try:
            r = live_get(surl, ua=UA, timeout=(20, 60))
        except Exception as exc:
            log.info("search fail %s: %s", surl, exc)
            continue
        for did in re.findall(r"/docs/(\d+)", r.text or ""):
            if did in seen:
                continue
            seen.add(did)
            items.append((did, f"https://lex.uz/docs/{did}", f"lex.uz/{did}"))
        # Also try docs from homepage
    try:
        r = live_get("https://lex.uz/", ua=UA)
        for did in re.findall(r"/docs/(\d+)", r.text or ""):
            if did not in seen:
                seen.add(did)
                items.append((did, f"https://lex.uz/docs/{did}", f"lex.uz/{did}"))
    except Exception as exc:
        log.info("home fail: %s", exc)
    log.info("catalog %s", len(items))
    return items


def extract_title(html: str, text: str, fallback: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if len(t) > 8:
            return t[:240]
    for line in text.splitlines():
        s = line.strip()
        if len(s) > 15:
            return s[:240]
    return fallback[:240]


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 50)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, hint in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=400)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Prefer raw HTML title if available
        raw_html = ""
        try:
            raw_html = (got.get("content") or b"").decode("utf-8", "replace")
        except Exception:
            raw_html = ""
        title = extract_title(raw_html, text, hint)
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_uz.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident, len(text))
        else:
            fail += 1
        time.sleep(0.25)
    write_summary(
        CC, country=COUNTRY, source="lex.uz National Database of Legislation",
        source_urls=["https://lex.uz/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="codes + search-backed incomplete",
        notes="Official lex.uz HTML consolidations. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
