#!/usr/bin/env python3
"""Uzbekistan: lex.uz official legislation HTML documents."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

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
    ("111149", "Конституция Республики Узбекистан"),
    ("107212", "Кодекс об административной ответственности"),
    ("111201", "Семейный кодекс"),
    ("111205", "Жилищный кодекс"),
    ("111137", "Налоговый кодекс"),
    ("111145", "Таможенный кодекс"),
    ("352012", "Бюджетный кодекс"),
    ("111161", "Земельный кодекс"),
    ("111165", "Лесной кодекс"),
    ("111169", "Водный кодекс"),
    ("111173", "Градостроительный кодекс"),
    ("106162", "Закон о судах"),
    ("47401", "Закон о нормативно-правовых актах"),
    ("111453", "Уголовно-процессуальный кодекс"),
    ("111193", "Гражданский процессуальный кодекс"),
    ("343001", "Экономический процессуальный кодекс"),
    ("41484", "Закон об образовании"),
]
SEARCHES = [
    "https://lex.uz/ru/search/nat?query=%D0%BA%D0%BE%D0%B4%D0%B5%D0%BA%D1%81&search_type=1",
    "https://lex.uz/search/nat?query=kodeks&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%B7%D0%B0%D0%BA%D0%BE%D0%BD&search_type=1",
    "https://lex.uz/search/nat?query=konstitutsiya&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%BD%D0%B0%D0%BB%D0%BE%D0%B3%D0%BE%D0%B2%D1%8B%D0%B9&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%BA%D0%BE%D0%BD%D1%81%D1%82%D0%B8%D1%82%D1%83%D1%86%D0%B8%D1%8F&search_type=1",
    "https://lex.uz/search/nat?query=qonun&search_type=1",
    "https://lex.uz/ru/search/nat?query=%D0%BF%D1%80%D0%B5%D0%B7%D0%B8%D0%B4%D0%B5%D0%BD%D1%82&search_type=1",
    "https://lex.uz/acts/list/codes",
    "https://lex.uz/ru/acts/list/codes",
    "https://lex.uz/acts/list/laws",
    "https://lex.uz/ru/acts/list/laws",
    "https://lex.uz/ru/",
]
# CDX of official lex.uz/docs/ HTML (official host only)
CDX_PREFIXES = (
    "lex.uz/docs/",
    "www.lex.uz/docs/",
    "lex.uz/ru/docs/",
)
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
    try:
        for prefix in CDX_PREFIXES:
            for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 1200), match_type="prefix"):
                orig = h.get("original") or ""
                m = re.search(r"/docs/(\d+)", orig)
                if not m:
                    continue
                did = m.group(1)
                if did in seen:
                    continue
                seen.add(did)
                items.append((did, f"https://lex.uz/docs/{did}", f"lex.uz/{did}"))
    except Exception as exc:
        log.info("cdx fail: %s", exc)
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
    max_new = env_int("MAX_NEW", 450)
    max_seconds = env_int("MAX_SECONDS", 7200)
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
        coverage="codes + search/CDX of lex.uz incomplete",
        notes="Official lex.uz HTML consolidations. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
