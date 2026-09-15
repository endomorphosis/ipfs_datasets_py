#!/usr/bin/env python3
"""Kazakhstan: Constitution + законы from ИПС «Әділет» (Ministry of Justice).

Official only:
  https://adilet.zan.kz  (Institute of Legislation and Legal Information, MOJ)
  HTTP host of the same system: http://insecure.zan.kz  (used when adilet.zan.kz TLS fails)

In-force catalog via public search facets (Форма акта):
  va=КОНТ constitution, va=КЗАК constitutional law, va=КОД code, va=ЗАК law
  st=yts|stp in-force (except constitutions: all published texts, small set)

Canonical source_url is always https://adilet.zan.kz/rus/docs/{id}.
Russian as published (Kazakh at /kaz/docs/{id}). Not paragraf.kz / zakon.kz commercial.
No WAF bypass. archive_fallbacks on HTTP 429 of official adilet.zan.kz URLs.
"""
from __future__ import annotations

import html as H
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "kz"
COUNTRY = "Kazakhstan"
SOURCE_TYPE = "adilet_zan_kz"
LICENSE = (
    "Official texts of the Republic of Kazakhstan as published in ИПС «Әділет» "
    "(Institute of Legislation and Legal Information of the Ministry of Justice). "
    "The authentic official publication / Әділет text prevails over this research "
    "snapshot. Not legal advice. Not paragraf.kz / commercial zakon.kz."
)
UA = DEFAULT_UA + " source=https://adilet.zan.kz/"
PORTAL = "https://adilet.zan.kz"
LIVE_HTTP = "http://insecure.zan.kz"  # official Adilet LIS over HTTP
SLEEP = 0.45
log = logging.getLogger("kz")

DOC_RE = re.compile(r'href="(/rus/docs/([A-Z][A-Za-z0-9_]+))"')
TITLE_RE = re.compile(
    r'href="(/rus/docs/[A-Z][A-Za-z0-9_]+)"[^>]*>(.*?)</a>', re.S | re.I
)
ART_KZ = re.compile(
    r"(?im)^\s*((?:Статья|Стаття|Бабы)\s+[0-9\u04d8\u04e8IVXLCDM]+[A-Za-zА-Яа-я]?)\b"
)
FORMS = [
    # (va, in_force_only, document_type, label)
    ("КОНТ", False, "constitution", "constitution"),
    ("КЗАК", True, "statute", "constitutional_law"),
    ("КОД", True, "statute", "code"),
    ("ЗАК", True, "statute", "law"),
]


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def canonical_doc(doc_id: str, lang: str = "rus") -> str:
    return f"{PORTAL}/{lang}/docs/{doc_id}"


def live_doc(doc_id: str, lang: str = "rus") -> str:
    return f"{LIVE_HTTP}/{lang}/docs/{doc_id}"


def rewrite_live(url: str) -> str:
    if "adilet.zan.kz" in url:
        return url.replace("https://adilet.zan.kz", LIVE_HTTP).replace(
            "http://adilet.zan.kz", LIVE_HTTP
        )
    return url


def get_official(url: str, *, timeout=(20, 90), retries: int = 3) -> dict:
    """Live GET of official Adilet; TLS-fail uses HTTP host; 429 -> archive of official URL."""
    official = url.replace(LIVE_HTTP, PORTAL).replace("http://adilet.zan.kz", PORTAL)
    if official.startswith("http://adilet"):
        official = official.replace("http://", "https://", 1)
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        if "adilet.zan.kz" in url:
            alt = rewrite_live(url)
            try:
                r = http_get(alt, ua=UA, sleep=SLEEP, timeout=timeout, retries=2)
                url = alt
            except Exception as exc2:
                log.info("http-host fail %s: %s — archive of official URL", alt, exc2)
                res = af.fetch_with_fallbacks(official, try_http=False)
                res.setdefault("retrieval", "archive")
                return res
        else:
            res = af.fetch_with_fallbacks(official, try_http=False)
            res.setdefault("retrieval", "archive")
            return res
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype) and body[:4] != b"%PDF":
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429 or (status in (403, 503) and text and af.is_challenge(text, status)):
        log.info("HTTP %s %s — archive_fallbacks of official URL", status, official)
        res = af.fetch_with_fallbacks(official, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and text and af.is_challenge(text, status) and len(text) < 8000:
        res = af.fetch_with_fallbacks(official, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and body:
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": official, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    res = af.fetch_with_fallbacks(official, try_http=False)
    res.setdefault("retrieval", "archive")
    return res


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def search_url(va: str, page: int, pagesize: int = 100, in_force: bool = True) -> str:
    q = f"pagesize={pagesize}&va={quote(va)}"
    if in_force:
        q += "&st=" + quote("yts|stp")
    if page > 1:
        q += f"&page={page}"
    return f"{LIVE_HTTP}/rus/search/docs/{q}"


def parse_listing(html: str, form: str, doc_type: str) -> list[dict]:
    out = []
    titles = {}
    for href, inner in TITLE_RE.findall(html or ""):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        titles[href.split("/")[-1]] = title
    seen = set()
    for href, doc_id in DOC_RE.findall(html or ""):
        if doc_id in seen:
            continue
        seen.add(doc_id)
        title = titles.get(doc_id) or doc_id
        out.append({
            "doc_id": doc_id,
            "url": canonical_doc(doc_id),
            "live_url": live_doc(doc_id),
            "title": title,
            "form": form,
            "document_type": "constitution" if (form == "constitution" or doc_id.startswith("K95") or doc_id.startswith("K26") or doc_id.startswith("K93")) else doc_type,
        })
    return out


def rss_count(va: str, in_force: bool) -> Optional[int]:
    q = f"rss=true&pagesize=5&va={quote(va)}"
    if in_force:
        q += "&st=" + quote("yts|stp")
    res = get_official(f"{LIVE_HTTP}/rus/search/docs/{q}")
    html = res.get("text") or ""
    m = re.search(r"Найдено\s+(\d+)\s+документ", html)
    return int(m.group(1)) if m else None


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 50:
        log.info("resume catalog n=%s", len(existing))
        return existing
    best: dict[str, dict] = {}
    for va, in_force, doc_type, form in FORMS:
        expected = rss_count(va, in_force)
        log.info("facet va=%s in_force=%s expected=%s", va, in_force, expected)
        page = 1
        empty = 0
        while page <= 80:
            url = search_url(va, page, in_force=in_force)
            res = get_official(url)
            html = res.get("text") or ""
            if res.get("status") != "success" or not html:
                log.warning("listing va=%s page=%s fail %s", va, page, res.get("error") or res.get("http_status"))
                empty += 1
                if empty >= 2:
                    break
                page += 1
                continue
            rows = parse_listing(html, form, doc_type)
            added = 0
            for row in rows:
                did = row["doc_id"]
                if did not in best:
                    best[did] = row
                    added += 1
            log.info("listing va=%s page=%s rows=%s added=%s unique=%s", va, page, len(rows), added, len(best))
            if not rows:
                empty += 1
                if empty >= 2:
                    break
            else:
                empty = 0
            if expected and len([x for x in best.values() if x.get("form") == form]) >= expected:
                break
            if len(rows) < 20:
                break
            page += 1
    # guarantee current + 1995 constitutions
    for did, title, form in (
        ("K2600000000", "Конституция Республики Казахстан", "constitution"),
        ("K950001000_", "Конституция Республики Казахстан", "constitution"),
    ):
        if did not in best:
            best[did] = {
                "doc_id": did, "url": canonical_doc(did), "live_url": live_doc(did),
                "title": title, "form": form, "document_type": "constitution",
            }
        else:
            best[did]["document_type"] = "constitution"
            best[did]["form"] = "constitution"
    items = list(best.values())
    items.sort(key=lambda x: (0 if x.get("document_type") == "constitution" else 1, x["doc_id"]))
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def extract_body(html: str) -> str:
    if not html:
        return ""
    chunk = html
    m = re.search(r"<h1[^>]*>.*?</h1>", html, re.I | re.S)
    if m:
        rest = html[m.start():]
        cut = re.search(
            r'(?:id="(?:comments|social|footer)"|class="(?:footer|share|banner)"|<footer)',
            rest, re.I,
        )
        chunk = rest[: cut.start()] if cut else rest[:1_200_000]
    text = html_to_text(chunk)
    # drop chrome
    text = re.sub(r"(?m)^(ҚАЗ|РУС|ENG|Поиск|Избранное|Печать)\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def split_kz(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_KZ.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9а-яё]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "adilet"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def parse_date(html: str, title: str) -> Optional[str]:
    m = re.search(
        r"(?:от|принята(?:я)?(?:\s+на\s+республиканском\s+референдуме)?)\s+"
        r"(\d{1,2}\s+[а-яё]+\s+\d{4}|\d{1,2}\.\d{1,2}\.\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})",
        html[:12000], re.I,
    )
    if m:
        raw = m.group(1)
        d = iso_date(raw)
        if d:
            return d
        months = {
            "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
            "мая": "05", "июня": "06", "июля": "07", "августа": "08",
            "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
        }
        mm = re.search(r"(\d{1,2})\s+([А-Яа-яA-Za-z]+)\s+(\d{4})", raw)
        if mm and mm.group(2).lower() in months:
            return f"{mm.group(3)}-{months[mm.group(2).lower()]}-{int(mm.group(1)):02d}"
    m = re.search(r"\b(19\d{2}|20\d{2})-(\d{2})-(\d{2})\b", html[:8000])
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def fetch_one(it: dict, done: set[str]) -> str:
    doc_id = it["doc_id"]
    ident = doc_id
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it["url"]
    res = get_official(it.get("live_url") or rewrite_live(url))
    html = res.get("text") or ""
    final = res.get("final_url") or res.get("wayback_url") or url
    if res.get("status") != "success" or len(html) < 200:
        log_failure(CC, {"id": rid, "url": url, "status": "failed",
                         "reason": res.get("error") or "empty", "retrieval": res.get("retrieval")})
        return "fail"
    text = extract_body(html)
    if len(text) < 120:
        text = html_to_text(html)
    if len(text) < 120:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("title") or ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if h1:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
        if t:
            title = t
    date = parse_date(html, title)
    is_const = it.get("document_type") == "constitution" or "конституция" in title.lower()
    repealed = bool(re.search(
        r"(?i)прекратил[ао]? действие|утратил[ао]? силу|күші жойылды|не действует",
        html[:20000],
    ))
    docs = split_kz(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="ru", ident=ident, title=title or ident,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_kz.py", date=date, official_identifier=doc_id,
        document_type="constitution" if is_const else "statute",
        law_status="repealed" if repealed else "current",
        is_current=False if repealed else True, documents=docs,
        extra_meta={
            "discovery": {"method": "adilet_search_facet", "form": it.get("form"), "doc_id": doc_id},
            "text_extraction": {"source": "official", "backend": "adilet-html"},
            "retrieval": {"method": res.get("retrieval") or res.get("method") or "live", "final_url": final},
            "kazakh_url": canonical_doc(doc_id, "kaz"),
        },
        extra_fields={"canonical_document_url": url, "information_url": url},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "ИПС «Әділет» (adilet.zan.kz), Institute of Legislation and Legal Information, "
        "Ministry of Justice. Constitution + in-force constitutional laws, codes and laws "
        "(Форма акта КОНТ/КЗАК/КОД/ЗАК; st=yts|stp for in-force). Russian as published; "
        "Kazakh URLs recorded. Live TLS to adilet.zan.kz failed from this host — texts from "
        "the official HTTP Adilet host insecure.zan.kz and archive_fallbacks of official "
        "adilet.zan.kz URLs on 429. Not paragraf.kz / commercial zakon.kz. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="ИПС «Әділет» / Ministry of Justice of Kazakhstan (adilet.zan.kz)",
        source_urls=[PORTAL + "/rus/", PORTAL + "/rus/search/docs/", PORTAL + "/rus/docs/K2600000000",
                     PORTAL + "/rus/docs/K950001000_"],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 20 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot"
    if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items):
        cov = "in-force-primary-legislation"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), "ok": counters["ok"], "skip": counters["skip"],
        "failed": counters["fail"], "coverage": cov, "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s coverage=%s", counters, cov)


if __name__ == "__main__":
    main()
