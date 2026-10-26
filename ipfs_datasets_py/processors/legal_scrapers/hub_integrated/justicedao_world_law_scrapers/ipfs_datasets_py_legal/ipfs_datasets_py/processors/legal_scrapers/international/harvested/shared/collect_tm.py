#!/usr/bin/env python3
"""Turkmenistan: free Mejlis (Parliament) + gov portal statute HTML only.

Official free sources:
  https://mejlis.gov.tm/laws?lang=ru  (+ AJAX ?ajax=true) → single-law/{id}
  https://mejlis.gov.tm/codes?lang=ru (+ AJAX) → single-code/{id}
  https://turkmenistan.gov.tm/ru/razdel/zakonodatelstvo (optional deepen)

SKIP paid Adalat DB: https://law.minjust.gov.tm/ (login + subscription).
No authentication, no WAF bypass. ≤1 req/s.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

CC = "tm"
COUNTRY = "Turkmenistan"
SOURCE_TYPE = "mejlis_gov_tm"
LICENSE = (
    "Official texts of Turkmenistan as published on the Mejlis (Parliament) website "
    "mejlis.gov.tm (and optionally turkmenistan.gov.tm legislation section). "
    "Free public HTML only — Adalat paid DB (law.minjust.gov.tm) intentionally excluded. "
    "Authentic official publication prevails. Not legal advice. Thin vs paid Adalat corpus."
)
UA = DEFAULT_UA + " source=https://mejlis.gov.tm/"
MEJLIS = "https://mejlis.gov.tm"
GOV = "https://turkmenistan.gov.tm"
SLEEP = float(os.environ.get("TM_SLEEP", "1.0"))
LANG = os.environ.get("TM_LANG", "ru")
MAX_LAWS = int(os.environ.get("TM_MAX_LAWS", "400"))
log = logging.getLogger("tm")

ART_RE = re.compile(
    r"(?im)^\s*((?:Статья|Madda|Article)\s+[0-9IVXLCDM]+[A-Za-zА-Яа-яё]?)(?:\.|\b)"
)
CHROME = re.compile(
    r"(?m)^(МЕДЖЛИС ТУРКМЕНИСТАНА|Mejlis|Русский|Türkmençe|English|Главная страница|"
    r"О Меджлисе|Законодательство|Кодексы|Законы|Подробно|Giňişleýin)\s*$"
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def polite_get(url: str, params=None, timeout=(20, 120)):
    if SLEEP:
        time.sleep(SLEEP)
    return http_get(url, ua=UA, sleep=0, timeout=timeout, params=params, retries=4)


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


def ajax_catalog(kind: str) -> list[dict]:
    """kind: laws | codes. Returns list of {id, title_ru, published_date}."""
    url = f"{MEJLIS}/{kind}"
    try:
        r = polite_get(url, params={"lang": LANG, "ajax": "true"})
    except Exception as exc:
        log.warning("ajax %s fail %s", kind, exc)
        return []
    if r.status_code != 200:
        log.warning("ajax %s http %s", kind, r.status_code)
        return []
    try:
        data = r.json()
    except Exception:
        # content-type may be text/html but body JSON
        try:
            data = json.loads(r.text)
        except Exception as exc:
            log.warning("ajax %s json fail %s body=%s", kind, exc, (r.text or "")[:200])
            return []
    if not isinstance(data, list):
        log.warning("ajax %s unexpected type %s", kind, type(data))
        return []
    (ROOT / CC / "raw").mkdir(parents=True, exist_ok=True)
    atomic_write(ROOT / CC / "raw" / f"ajax_{kind}.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    log.info("ajax %s n=%s", kind, len(data))
    return data


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 15 and os.environ.get("TM_REDISCOVER") != "1":
        log.info("resume catalog n=%s", len(existing))
        return existing
    best: dict[str, dict] = {}

    codes = ajax_catalog("codes")
    for rec in codes:
        sid = str(rec.get("id") or "").strip()
        if not sid:
            continue
        key = f"code-{sid}"
        title = (rec.get("title_ru") or rec.get("title_tm") or rec.get("title_en") or f"code {sid}").strip()
        date = iso_date(str(rec.get("published_date") or "")[:10])
        best[key] = {
            "doc_id": key,
            "kind": "code",
            "numeric_id": sid,
            "url": f"{MEJLIS}/single-code/{sid}?lang={LANG}",
            "title": title,
            "document_type": "statute",
            "form": "code",
            "date": date,
        }

    laws = ajax_catalog("laws")
    n_laws = 0
    for rec in laws:
        if n_laws >= MAX_LAWS:
            break
        sid = str(rec.get("id") or "").strip()
        if not sid:
            continue
        key = f"law-{sid}"
        title = (rec.get("title_ru") or rec.get("title_tm") or rec.get("title_en") or f"law {sid}").strip()
        # Skip empty / placeholder
        if not title or title.lower() in {"none", "null"}:
            continue
        date = iso_date(str(rec.get("published_date") or "")[:10])
        is_const = bool(re.search(r"(?i)конституци", title)) and "закон" not in title.lower()[:20]
        best[key] = {
            "doc_id": key,
            "kind": "law",
            "numeric_id": sid,
            "url": f"{MEJLIS}/single-law/{sid}?lang={LANG}",
            "title": title,
            "document_type": "constitution" if is_const else "statute",
            "form": "constitution" if is_const else "law",
            "date": date,
        }
        n_laws += 1

    # Optional: gov portal listing (HTML links to law posts)
    try:
        r = polite_get(f"{GOV}/ru/razdel/zakonodatelstvo")
        if r.status_code == 200 and BeautifulSoup is not None:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href]"):
                href = a.get("href") or ""
                if "zakon" not in href.lower() and "kanun" not in href.lower() and "/ru/" not in href:
                    continue
                if href.startswith("/"):
                    href = GOV + href
                if "turkmenistan.gov.tm" not in href:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:400]
                if len(title) < 20:
                    continue
                key = "gov-" + re.sub(r"[^a-z0-9]+", "-", href.lower())[:120]
                if key in best:
                    continue
                # Only add a small sample of gov posts to avoid duplicates of Mejlis texts
                if sum(1 for x in best.values() if x.get("form") == "gov") >= 30:
                    break
                best[key] = {
                    "doc_id": key,
                    "kind": "gov",
                    "numeric_id": "",
                    "url": href,
                    "title": title,
                    "document_type": "statute",
                    "form": "gov",
                    "date": None,
                }
            log.info("gov portal extras=%s", sum(1 for x in best.values() if x.get("form") == "gov"))
    except Exception as exc:
        log.info("gov portal skip: %s", exc)

    # Explicitly record Adalat SKIP
    skip_note = {
        "skipped_source": "https://law.minjust.gov.tm/",
        "reason": "paid Adalat subscription / login wall — out of scope for free harvest",
    }
    atomic_write(ROOT / CC / "raw" / "SKIP_adalat.json", json.dumps(skip_note, ensure_ascii=False, indent=2) + "\n")

    items = list(best.values())
    items.sort(key=lambda x: (
        0 if x.get("document_type") == "constitution" else 1,
        0 if x.get("form") == "code" else 1,
        0 if x.get("form") == "law" else 1,
        x["doc_id"],
    ))
    save_catalog(items)
    log.info("catalog n=%s (codes=%s laws=%s gov=%s)", len(items),
             sum(1 for x in items if x["form"] == "code"),
             sum(1 for x in items if x["form"] == "law"),
             sum(1 for x in items if x["form"] == "gov"))
    return items


def extract_body(html: str) -> tuple[str, str]:
    if not html:
        return "", ""
    if BeautifulSoup is None:
        text = html_to_text(html)
        return "", CHROME.sub("", text).strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    # Prefer main content containers
    main = None
    for sel in [".single_law_content", ".law_text", ".content_text", ".news-detail",
                ".container .content", "article", ".main_content", "#content"]:
        main = soup.select_one(sel)
        if main and len(main.get_text(strip=True)) > 200:
            break
    node = main or soup.body or soup
    text = node.get_text("\n", strip=True)
    text = CHROME.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = ""
    h = soup.find(["h1", "h2", "h3"])
    if h:
        title = re.sub(r"\s+", " ", h.get_text(" ", strip=True))[:500]
    if not title:
        for line in text.splitlines():
            if len(line) > 20 and "МЕДЖЛИС" not in line and "Mejlis" not in line:
                title = line[:500]
                break
    return title, text


def split_tm(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_RE.finditer(text or ""))
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
            "metadata": {"text_extraction": {"source": "official", "backend": "mejlis-html"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def fetch_one(it: dict, done: set[str]) -> str:
    did = it["doc_id"]
    rid = slug_id(CC, did)
    if rid in done:
        return "skip"
    url = it["url"]
    # Never hit Adalat
    if "law.minjust.gov.tm" in url:
        log_failure(CC, {"id": rid, "url": url, "status": "skipped", "reason": "adalat_paid_skip"})
        return "skip"
    try:
        r = polite_get(url)
    except Exception as exc:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": repr(exc)})
        return "fail"
    html = r.text or ""
    if r.status_code != 200 or len(html) < 400:
        log_failure(CC, {"id": rid, "url": url, "status": "failed",
                         "reason": f"http_{r.status_code}", "len": len(html)})
        return "fail"
    if "/login" in (r.url or "") and "law.minjust" in (r.url or ""):
        log_failure(CC, {"id": rid, "url": url, "status": "skipped", "reason": "redirect_adalat_login"})
        return "skip"
    title_guess, text = extract_body(html)
    if len(text) < 150:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    # Require statute-like substance (avoid chrome-only pages)
    if len(text) < 400 and not re.search(r"Статья|Madda|Кодекс|Закон|Kanun", text):
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "too_thin"})
        return "fail"
    title = it.get("title") or title_guess or did
    if title_guess and re.search(r"(Закон|Кодекс|Конституц|Kanun)", title_guess, re.I):
        if len(title_guess) > 15:
            title = title_guess
    date = it.get("date")
    is_const = it.get("document_type") == "constitution" or bool(
        re.match(r"(?i)конституция\b", title.strip())
    )
    docs = split_tm(text, rid, url, date)
    lang = "ru" if LANG == "ru" else ("tk" if LANG == "tm" else LANG)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=did, title=title[:500],
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_tm.py", date=date,
        official_identifier=str(it.get("numeric_id") or did),
        document_type="constitution" if is_const else "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": "mejlis_ajax_catalog", "form": it.get("form"),
                          "kind": it.get("kind"), "numeric_id": it.get("numeric_id")},
            "text_extraction": {"source": "official", "backend": "mejlis-html"},
            "retrieval": {"method": "live", "http_status": r.status_code},
            "corpus_note": "free Mejlis/gov HTML only; Adalat paid DB skipped",
        },
        extra_fields={"canonical_document_url": url, "information_url": url},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Free Mejlis.gov.tm AJAX catalogs (laws/codes) + single-law / single-code HTML. "
        "Optional turkmenistan.gov.tm /razdel/zakonodatelstvo extras. "
        "SKIP paid Adalat law.minjust.gov.tm (login+subscription). "
        "Corpus is intentionally thin vs Adalat's paid set. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Mejlis of Turkmenistan (mejlis.gov.tm) free HTML; Adalat paid DB skipped",
        source_urls=[
            MEJLIS + "/",
            MEJLIS + "/laws?lang=ru",
            MEJLIS + "/codes?lang=ru",
            GOV + "/ru/razdel/zakonodatelstvo",
            "SKIP: https://law.minjust.gov.tm/",
        ],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    if not items:
        write_summary(
            CC, country=COUNTRY,
            source="Mejlis free portals — discovery empty",
            source_urls=[MEJLIS + "/", "SKIP: https://law.minjust.gov.tm/"],
            license_text=LICENSE, discovered=0, fetched=0, skipped=0, failed=0,
            coverage="empty",
            notes="No free Mejlis/gov statute texts discovered this run. Adalat paid DB skipped by policy.",
        )
        log.error("empty catalog — writing SKIP-oriented SUMMARY")
        return
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
            log.exception("fetch fail %s", it.get("doc_id"))
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot-free-mejlis"
    if counters["ok"] + counters["skip"] >= 20:
        cov = "free-mejlis-codes-laws-batch"
    elif counters["ok"] == 0:
        cov = "SKIP-or-empty-free-portals"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), "ok": counters["ok"], "skip": counters["skip"],
        "failed": counters["fail"], "coverage": cov, "started": t0, "finished": utcnow(),
        "adalat_skipped": True,
    }, indent=2) + "\n")
    log.info("done %s coverage=%s", counters, cov)


if __name__ == "__main__":
    main()
