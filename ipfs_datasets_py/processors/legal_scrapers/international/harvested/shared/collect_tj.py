#!/usr/bin/env python3
"""Tajikistan: Constitution/codes/laws from MoJ Adlia (mmih.tj) public DocumentView HTML.

Official only:
  https://mmih.tj/SEARCH?doc_type={1,2,4}
  https://mmih.tj/SEARCH/DocumentView?DocumentId={id}
Secondary mmk.tj may 503 — optional, not required.

doc_type: 1=Конститутсия (facet observed unreliable), 2=Кодексҳо, 4=Қонун.
Stay on free public HTML; do not login/subscribe. ≤1 req/s. No WAF bypass.
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
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

CC = "tj"
COUNTRY = "Tajikistan"
SOURCE_TYPE = "mmih_tj_adlia"
LICENSE = (
    "Official texts of the Republic of Tajikistan as published in the Ministry of Justice "
    "Centralized Bank «Adlia» (mmih.tj). The authentic official publication prevails over "
    "this research snapshot. Not legal advice. Free public DocumentView only."
)
UA = DEFAULT_UA + " source=https://mmih.tj/"
PORTAL = "https://mmih.tj"
SLEEP = float(os.environ.get("TJ_SLEEP", "1.0"))
MAX_LAWS = int(os.environ.get("TJ_MAX_LAWS", "280"))
MAX_CODES = int(os.environ.get("TJ_MAX_CODES", "80"))
log = logging.getLogger("tj")

DOC_TYPES = [
    # (doc_type, form, document_type, max_items)
    ("1", "constitution", "constitution", 80),
    ("2", "code", "statute", MAX_CODES),
    ("4", "law", "statute", MAX_LAWS),
]

ART_RE = re.compile(
    r"(?im)^\s*((?:Моддаи|Модда|Статья|Article)\s+[0-9IVXLCDM]+[A-Za-zА-Яа-яё]?)(?:\.|\b)"
)
CHROME = re.compile(
    r"(?m)^(Menu|ADLIA|DLIA|Маълумот|Классификатор|Содиркунанда|Русский|Тоҷикӣ|"
    r"English|Дохилшавӣ|×|Тоҷикӣ - русӣ)\s*$"
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


def polite_get(url: str, **kw):
    if SLEEP:
        time.sleep(SLEEP)
    return http_get(url, ua=UA, sleep=0, timeout=kw.get("timeout", (20, 120)), retries=kw.get("retries", 4))


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


def parse_listing(html: str, form: str, doc_type: str) -> list[dict]:
    out = []
    if not html:
        return out
    if BeautifulSoup is None:
        for did in dict.fromkeys(re.findall(r"DocumentView\?DocumentId=(\d+)", html)):
            out.append({
                "doc_id": did,
                "url": f"{PORTAL}/SEARCH/DocumentView?DocumentId={did}",
                "title": f"DocumentId {did}",
                "form": form,
                "document_type": doc_type,
                "status": "",
                "date": None,
            })
        return out
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for a in soup.select('a[href*="DocumentView"]'):
        href = a.get("href") or ""
        m = re.search(r"DocumentId=(\d+)", href)
        if not m:
            continue
        did = m.group(1)
        if did in seen:
            continue
        seen.add(did)
        row = a.find_parent("tr")
        txt = row.get_text(" ", strip=True) if row else a.get_text(" ", strip=True)
        txt = re.sub(r"\s+", " ", txt or "").strip()
        # title: drop trailing status/date tokens somewhat
        title = txt
        status = ""
        if "Амалкунанда" in txt:
            status = "current"
        elif re.search(r"Қувваи худро гум кардааст|Утратил", txt, re.I):
            status = "repealed"
        date = None
        dm = re.search(r"(\d{2}\.\d{2}\.\d{4})", txt)
        if dm:
            date = iso_date(dm.group(1))
        # Heuristic: constitution facet often returns non-constitution docs — keep typed as statute unless title says otherwise
        dtype = doc_type
        form2 = form
        low = title.lower()
        if "конститутсияи ҷумҳурии" in low or "конституция республики таджикистан" in low:
            if "тағйир" not in low and "илова" not in low and "қарор" not in low:
                dtype = "constitution"
                form2 = "constitution"
        elif form == "constitution" and not re.search(r"конститутси", low):
            # mis-faceted row: still harvest but as statute
            dtype = "statute"
            form2 = "misc_from_const_facet"
        out.append({
            "doc_id": did,
            "url": urljoin(PORTAL, href),
            "title": title[:500] or f"DocumentId {did}",
            "form": form2,
            "document_type": dtype,
            "status": status,
            "date": date,
        })
    return out


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 20 and os.environ.get("TJ_REDISCOVER") != "1":
        log.info("resume catalog n=%s", len(existing))
        return existing
    best: dict[str, dict] = {}
    for dtype, form, doc_type, cap in DOC_TYPES:
        url = f"{PORTAL}/SEARCH?doc_type={dtype}"
        try:
            r = polite_get(url)
            html = r.text or ""
        except Exception as exc:
            log.warning("listing doc_type=%s fail %s", dtype, exc)
            continue
        if r.status_code != 200 or len(html) < 500:
            log.warning("listing doc_type=%s http=%s len=%s", dtype, r.status_code, len(html))
            continue
        # Paywall / login wall cue
        if re.search(r"(?i)subscribe|тариф|оплат|paywall", html) and "DocumentView" not in html:
            log.error("listing appears gated — abort facet %s", dtype)
            continue
        rows = parse_listing(html, form, doc_type)
        added = 0
        for row in rows:
            if len([x for x in best.values() if x.get("form") == form or (form == "law" and x.get("form") == "law")]) >= cap and row["doc_id"] not in best:
                # soft cap by intended form
                pass
            if row["doc_id"] in best:
                # upgrade constitution typing
                if row["document_type"] == "constitution":
                    best[row["doc_id"]]["document_type"] = "constitution"
                    best[row["doc_id"]]["form"] = "constitution"
                continue
            # apply caps per form
            n_form = sum(1 for x in best.values() if x.get("form") == row["form"] or (row["form"] == form and x.get("form") == form))
            # simpler cap: by requested facet form
            n_facet = sum(1 for x in best.values() if x.get("_facet") == form)
            if n_facet >= cap:
                continue
            row = dict(row)
            row["_facet"] = form
            best[row["doc_id"]] = row
            added += 1
        log.info("facet doc_type=%s form=%s rows=%s added=%s unique=%s", dtype, form, len(rows), added, len(best))
        # Persist raw listing snippet
        (ROOT / CC / "raw").mkdir(parents=True, exist_ok=True)
        atomic_write(ROOT / CC / "raw" / f"listing_doc_type_{dtype}.html", html[:500000])

    # POST search for codes/laws keywords to deepen if thin
    if sum(1 for x in best.values() if x.get("form") == "code") < 10:
        try:
            if SLEEP:
                time.sleep(SLEEP)
            r = get_session(UA).post(
                f"{PORTAL}/SEARCH/Index",
                data={"DocumentText": "", "DocumentNumber": "", "DocumentDate": "",
                      "DocumentType": "2", "EmitentId": "", "DocCategory": ""},
                timeout=(20, 90),
                headers={"User-Agent": UA, "Referer": f"{PORTAL}/SEARCH"},
            )
            for row in parse_listing(r.text or "", "code", "statute"):
                if row["doc_id"] not in best:
                    row["_facet"] = "code"
                    best[row["doc_id"]] = row
        except Exception as exc:
            log.info("POST codes fail: %s", exc)

    items = list(best.values())
    items.sort(key=lambda x: (
        0 if x.get("document_type") == "constitution" else 1,
        0 if x.get("form") == "code" else 1,
        0 if x.get("form") == "law" else 1,
        x["doc_id"],
    ))
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def extract_body(html: str) -> tuple[str, str]:
    """Return (title, text)."""
    if not html:
        return "", ""
    if BeautifulSoup is None:
        text = html_to_text(html)
        text = CHROME.sub("", text)
        return "", re.sub(r"\n{3,}", "\n\n", text).strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = CHROME.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = ""
    for line in text.splitlines():
        s = line.strip()
        if len(s) < 20:
            continue
        if s in {"Menu", "ADLIA", "DLIA"}:
            continue
        if re.match(r"^(Маълумот|Классификатор|Содиркунанда|Русский|Тоҷикӣ|English)", s):
            continue
        title = s[:500]
        break
    return title, text


def split_tj(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
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
            "metadata": {"text_extraction": {"source": "official", "backend": "adlia-html"}},
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
    # Login/paywall detection on body
    if re.search(r"(?i)please\s+log\s*in|требуется\s+авторизация", html) and len(html) < 8000:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "login_wall"})
        return "fail"
    title_guess, text = extract_body(html)
    if len(text) < 120:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("title") or title_guess or f"DocumentId {did}"
    # Prefer extracted instrument title when listing title is noisy
    if title_guess and (title.startswith("DocumentId") or len(title_guess) > 30):
        if not title.lower().startswith(title_guess.lower()[:20]):
            # keep listing title if it looks like a law name
            if not re.search(r"(Қонун|Кодекс|Конститут|Закон)", title, re.I) and re.search(
                r"(Қонун|Кодекс|Конститут|Закон|Низомнома)", title_guess, re.I
            ):
                title = title_guess
    date = it.get("date")
    is_const = it.get("document_type") == "constitution" or bool(
        re.search(r"(?i)конститутсияи\s+ҷумҳурии\s+тоҷикистон|конституция\s+республики\s+таджикистан", title)
    )
    repealed = it.get("status") == "repealed" or bool(
        re.search(r"(?i)қувваи\s+худро\s+гум|утратил[ао]?\s+силу", title + "\n" + text[:2000])
    )
    # Language heuristic
    lang = "tg"
    if re.search(r"\b(Статья|Республики Таджикистан|настоящий Кодекс)\b", text[:3000]):
        if not re.search(r"Моддаи?\s+\d+", text[:5000]):
            lang = "ru"
    docs = split_tj(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=did, title=title[:500],
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_tj.py", date=date, official_identifier=did,
        document_type="constitution" if is_const else "statute",
        law_status="repealed" if repealed else "current",
        is_current=False if repealed else True, documents=docs,
        extra_meta={
            "discovery": {"method": "mmih_search_doc_type", "form": it.get("form"),
                          "facet": it.get("_facet"), "document_id": did},
            "text_extraction": {"source": "official", "backend": "adlia-DocumentView-html"},
            "retrieval": {"method": "live", "http_status": r.status_code},
        },
        extra_fields={"canonical_document_url": url, "information_url": url},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Adlia (mmih.tj) free public SEARCH + DocumentView HTML. "
        "Facets doc_type=1 (constitution label; facet content often misaligned), "
        f"doc_type=2 codes (cap {MAX_CODES}), doc_type=4 laws (cap {MAX_LAWS}). "
        "mmk.tj legislation secondary skipped when 503. No login/subscription. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="MoJ Adlia / mmih.tj (Tajikistan)",
        source_urls=[
            PORTAL + "/SEARCH",
            PORTAL + "/SEARCH?doc_type=4",
            PORTAL + "/SEARCH?doc_type=2",
            PORTAL + "/SEARCH?doc_type=1",
            "https://mmk.tj/legislation",
        ],
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
            log.exception("fetch fail %s", it.get("doc_id"))
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot"
    if counters["ok"] + counters["skip"] >= 20:
        cov = "adlia-codes-laws-batch"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), "ok": counters["ok"], "skip": counters["skip"],
        "failed": counters["fail"], "coverage": cov, "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s coverage=%s", counters, cov)


if __name__ == "__main__":
    main()
